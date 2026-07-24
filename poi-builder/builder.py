import json,math,re,unicodedata,sys,time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import pycountry
from overturemaps import record_batch_reader

IN=Path('seed.json'); OUT=Path('countries_destinations_with_top_20_pois.json')
CATS=('tourist_attraction','restaurant','hotel','bar'); Q={c:5 for c in CATS}
RX={
'bar':re.compile(r'(^|_)(bar|pub|nightclub|cocktail_bar|wine_bar|sports_bar|lounge|beer_garden|brewpub|tavern|distillery|taproom)($|_)'),
'hotel':re.compile(r'(^|_)(hotel|motel|hostel|resort|inn|guest_house|bed_and_breakfast|boutique_hotel|aparthotel|lodging|accommodation)($|_)'),
'restaurant':re.compile(r'(^|_)(restaurant|cafe|coffee_shop|bakery|bistro|diner|pizzeria|steakhouse|food_court|ice_cream|tea_room|brasserie|grill|eatery|taqueria|trattoria|fast_food)($|_)'),
'tourist_attraction':re.compile(r'(^|_)(tourist_attraction|landmark|historic|monument|memorial|museum|gallery|castle|palace|fort|archaeological_site|cathedral|basilica|temple|mosque|synagogue|church|viewpoint|scenic_lookout|zoo|aquarium|botanical_garden|theme_park|amusement_park|national_park|state_park|urban_park|park|garden|beach|waterfall|cave|stadium|arena|opera_house|performing_arts_venue)($|_)')}

def norm(s):
 s=unicodedata.normalize('NFKD',str(s or '')); return re.sub(r'[^a-z0-9]+',' ',''.join(c for c in s if not unicodedata.combining(c)).lower()).strip()
def point(s):
 m=re.match(r'Point\(([-\d.]+)\s+([-\d.]+)\)',s); return float(m.group(1)),float(m.group(2))
def hav(a,b,c,d):
 p1,p2=math.radians(a),math.radians(c); dp=math.radians(c-a); dl=math.radians(d-b); x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2; return 12742.0176*math.asin(math.sqrt(x))
def first(x):
 if isinstance(x,list): return x[0] if x else None
 return x
def category(v):
 vals=[]
 if isinstance(v,dict): vals=[v.get('primary')]+list(v.get('alternate') or [])
 elif v: vals=[v]
 text='_'.join(norm(x).replace(' ','_') for x in vals if x)
 for c in ('bar','hotel','restaurant','tourist_attraction'):
  if RX[c].search(text): return c
 return None
def name_of(v):
 if not isinstance(v,dict): return str(v or '').strip() or None
 return v.get('primary') or first(v.get('common')) or None
def addr_of(v):
 a=first(v); return a if isinstance(a,dict) else {}
def source_count(v): return len(v) if isinstance(v,list) else 0
def clean_url(v): return first(v) if isinstance(v,list) else v
def bbox(lat,lon,km=35):
 dy=km/110.574; dx=km/max(20,111.32*math.cos(math.radians(lat))); return (lon-dx,lat-dy,lon+dx,lat+dy)
def target_rows(seed):
 out=[]; targets=[]; tid=0
 for ce in seed:
  seen=set(); cities=[]
  for r in sorted(ce.get('attractions',[]),key=lambda z:-float(z.get('popularity_score') or 0)):
   k=norm(r['city'])
   if not k or k in seen: continue
   seen.add(k); lon,lat=point(r['coords']); cities.append({'city':r['city'],'coords':r['coords'],'popularity_score':str(r.get('popularity_score','')),'pois':[]})
   targets.append({'id':tid,'country':ce['country'],'country2':pycountry.countries.get(alpha_3=ce['country']).alpha_2,'city':r['city'],'lat':lat,'lon':lon}); tid+=1
   if len(cities)==10: break
  out.append({'country':ce['country'],'attractions':cities})
 return out,targets

def fetch(t):
 err=None
 for attempt in range(4):
  try:
   rd=record_batch_reader('place',bbox=bbox(t['lat'],t['lon']))
   if rd is None:return t['id'],[]
   rows=[]
   for batch in rd:
    for r in batch.to_pylist():
     if str(r.get('operating_status') or '').lower() in ('closed_permanently','closed'): continue
     c=category(r.get('categories'))
     if not c: continue
     n=name_of(r.get('names'))
     if not n or len(norm(n))<2: continue
     bb=r.get('bbox') or {}; lon=float(bb.get('xmin')); lat=float(bb.get('ymin')); d=hav(t['lat'],t['lon'],lat,lon)
     if d>40:continue
     a=addr_of(r.get('addresses')); conf=float(r.get('confidence') or 0); sc=source_count(r.get('sources'))
     completeness=sum(bool(x) for x in (r.get('websites'),r.get('phones'),r.get('socials'),a.get('freeform'),a.get('locality')))
     score=conf*55+min(sc,5)*5+completeness*3+max(0,15-d*.375)
     rows.append({'name':n,'category':c,'subcategory':(r.get('categories') or {}).get('primary') if isinstance(r.get('categories'),dict) else None,'latitude':round(lat,7),'longitude':round(lon,7),'distance_km':round(d,3),'address':a.get('freeform'),'locality':a.get('locality'),'region':a.get('region'),'postcode':a.get('postcode'),'website':clean_url(r.get('websites')),'phone':clean_url(r.get('phones')),'ranking_score':round(score,3),'source':'Overture Maps Places','source_id':r.get('id'),'source_confidence':round(conf,6),'provider_count':sc})
   return t['id'],rows
  except Exception as e: err=e; time.sleep(3*(attempt+1))
 print('FAILED',t['country'],t['city'],repr(err),file=sys.stderr); return t['id'],[]
def select(rows):
 seen=set(); u=[]
 for r in sorted(rows,key=lambda x:(-x['ranking_score'],x['distance_km'],x['name'])):
  k=(norm(r['name']),round(r['latitude'],4),round(r['longitude'],4))
  if k in seen:continue
  seen.add(k); u.append(r)
 by=defaultdict(list)
 for r in u:by[r['category']].append(r)
 s=[]; sk=set()
 for c in CATS:
  for r in by[c][:Q[c]]:s.append(r);sk.add(id(r))
 for r in u:
  if len(s)>=20:break
  if id(r) not in sk:s.append(r);sk.add(id(r))
 s=sorted(s[:20],key=lambda x:(-x['ranking_score'],x['distance_km'],x['name']))
 for i,r in enumerate(s,1):r['rank']=i
 return [{k:v for k,v in ({'rank':r['rank']}|r).items() if v not in (None,'',[])} for r in s]
def main():
 seed=json.load(open(IN,encoding='utf-8')); out,targets=target_rows(seed); results={}; done=0
 with ThreadPoolExecutor(max_workers=6) as ex:
  fut=[ex.submit(fetch,t) for t in targets]
  for f in as_completed(fut):
   i,rows=f.result();results[i]=select(rows);done+=1
   if done%25==0:print(f'{done}/{len(targets)}',flush=True)
 tid=0; short=[]
 for ce in out:
  for city in ce['attractions']:
   city['pois']=results.get(tid,[])
   if len(city['pois'])<20:short.append({'country':ce['country'],'city':city['city'],'count':len(city['pois'])})
   tid+=1
 json.dump(out,open(OUT,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'),allow_nan=False)
 json.dump({'countries':len(out),'cities':len(targets),'pois':sum(len(x['pois']) for c in out for x in c['attractions']),'cities_below_20':short},open('poi_stats.json','w'),indent=2)
 print('DONE',OUT.stat().st_size,'short',len(short))
if __name__=='__main__':main()
