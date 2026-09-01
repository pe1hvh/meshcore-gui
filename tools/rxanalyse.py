cat > /tmp/rxanalyse.py << 'EOF'
import json, collections, statistics

F="/home/hans/.meshcore-gui/archive/_dev_ttyUSB1_rxlog.jsonl"
per_dag=collections.Counter(); adv_dag=collections.Counter()
snr_dag=collections.defaultdict(list); rssi_dag=collections.defaultdict(list)
buren=collections.defaultdict(collections.Counter); uniek=collections.defaultdict(set)
types=collections.defaultdict(collections.Counter)

for r in open(F,encoding="utf-8",errors="replace"):
    r=r.strip()
    if not r: continue
    try: o=json.loads(r)
    except: continue
    ts=o.get("timestamp_utc","")
    if len(ts)<10: continue
    d=ts[:10]
    per_dag[d]+=1
    types[d][o.get("payload_type","?")]+=1
    if o.get("payload_type")=="Advert": adv_dag[d]+=1
    if isinstance(o.get("snr"),(int,float)): snr_dag[d].append(o["snr"])
    if isinstance(o.get("rssi"),(int,float)): rssi_dag[d].append(o["rssi"])
    pn=o.get("path_names") or []
    if pn:
        laatste=pn[-1]
        buren[laatste][d]+=1
        uniek[d].add(laatste)

dagen=sorted(per_dag)
print("datum        totaal  advert  uniek  medSNR  medRSSI")
for d in dagen:
    s=statistics.median(snr_dag[d]) if snr_dag[d] else 0
    rs=statistics.median(rssi_dag[d]) if rssi_dag[d] else 0
    print(f"{d}  {per_dag[d]:6d}  {adv_dag[d]:6d}  {len(uniek[d]):5d}  {s:6.1f}  {rs:7.0f}")

print("\n=== per laatste-hop node (top 15) ===")
top=sorted(buren, key=lambda n: -sum(buren[n].values()))[:15]
print(f"{'node':32s} " + " ".join(x[5:] for x in dagen))
for n in top:
    print(f"{n[:32]:32s} " + " ".join(f"{buren[n].get(d,0):5d}" for d in dagen))

print("\n=== payload-types per dag ===")
allt=sorted({t for d in types for t in types[d]})
print(f"{'datum':12s} " + " ".join(f"{t[:9]:>9s}" for t in allt))
for d in dagen:
    print(f"{d:12s} " + " ".join(f"{types[d].get(t,0):9d}" for t in allt))
EOF
python3 /tmp/rxanalyse.py
