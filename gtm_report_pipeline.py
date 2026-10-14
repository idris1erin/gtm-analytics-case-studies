#!/usr/bin/env python3
# =============================================================================
#  GTM OPERATING REVIEW  —  end-to-end revenue-analytics pipeline
#  -----------------------------------------------------------------------------
#  One script that reads the Salesforce-style CSV exports from a folder and
#  produces (1) a one-page executive dashboard PNG and (2) a full multi-section
#  PDF case-study report.  Re-export the reports into the folder (same file
#  names) and re-run to refresh everything.
#
#  REQUIRES :  pandas, numpy, matplotlib, seaborn   (pip install ...)
#  OPTIONAL :  playwright  (for the polished PDF)
#              pip install playwright && playwright install chromium
#              -- if Playwright is missing, the script still builds the dashboard
#                 and writes the report as HTML; open it and Print -> Save as PDF.
#
#  RUN      :  python3 gtm_report_pipeline.py
#  DATA     :  by default reads the ./data folder next to this script.
#              Override with env vars GTM_DATA (inputs) / GTM_OUT (outputs).
#  AUTHOR   :  Idris E  —  synthetic data, portfolio case study
# =============================================================================

import os, base64, datetime
import pandas as pd, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, seaborn as sns
from matplotlib import gridspec

# ------------------------------------------------------------------ CONFIG ----
# Paths resolve relative to this script, so the repo is portable (no personal paths).
HERE        = os.path.dirname(os.path.abspath(__file__))
DATA_FOLDER = os.path.join(os.environ.get("GTM_DATA", os.path.join(HERE, "data")), "")  # inputs; trailing sep
OUT_FOLDER  = os.path.join(os.environ.get("GTM_OUT",  HERE), "")                         # outputs land next to script
ASSET_DIR   = os.path.join(OUT_FOLDER, "_report_assets") + os.sep
os.makedirs(ASSET_DIR, exist_ok=True)

# brand palette (single source of truth for every chart + the report CSS)
NAVY="#1F3A5F"; TEAL="#2A9D8F"; ORANGE="#E76F51"; GOLD="#E9C46A"
SLATE="#6B7A8F"; GREEN="#2F6B2F"; LIGHT="#EEF2F6"
THEATER_C={"Americas":NAVY,"EMEA":TEAL,"APJ":GOLD,"PubSec":ORANGE}
sns.set_style("whitegrid")
plt.rcParams.update({"axes.titleweight":"bold","axes.titlesize":13,"font.size":11})

# =========================================================== 1. LOAD DATA =====
# Each CSV stands in for a scheduled Salesforce report export.
REPORTS = {"opportunities.csv":"Opportunity report (open + closed)",
           "accounts.csv":"Account / install-base report",
           "fact_bookings.csv":"Bookings — closed won",
           "dim_sales_org.csv":"Rep roster, quota & pipeline",
           "targets.csv":"Quota / target plan"}
_missing=[f for f in REPORTS if not os.path.exists(DATA_FOLDER+f)]
if _missing:
    raise SystemExit(f"Missing report files in {DATA_FOLDER}: {_missing}")

accounts = pd.read_csv(DATA_FOLDER+"accounts.csv")
opps     = pd.read_csv(DATA_FOLDER+"opportunities.csv")
fact     = pd.read_csv(DATA_FOLDER+"fact_bookings.csv")
sales    = pd.read_csv(DATA_FOLDER+"dim_sales_org.csv")
targets  = pd.read_csv(DATA_FOLDER+"targets.csv")
print(f"Loaded 5 reports from {DATA_FOLDER}  ({datetime.datetime.now():%Y-%m-%d %H:%M})")

# =========================================================== 2. METRICS =======
nb = fact[fact.deal_type=="New Business"].copy()
rep_nbb = nb.groupby("rep_id").nbb_arr.sum().rename("nbb_actual")
att = sales.merge(rep_nbb, on="rep_id", how="left").fillna({"nbb_actual":0})
att["attainment_pct"] = att.nbb_actual/att.annual_nbb_quota*100          # attainment = NBB / quota

closed = opps[opps.is_closed]
openo  = opps[~opps.is_closed].copy(); openo["weighted"]=openo.amount_arr*openo.probability

K = dict(nbb=nb.nbb_arr.sum(), tgt=targets.nbb_target.sum(),
         ren=fact[fact.deal_type=="Renewal"].nbb_arr.sum(),
         exp=fact[fact.deal_type=="Expansion"].nbb_arr.sum(),
         win=opps.is_won.sum()/len(closed)*100, cov=sales.pipeline_coverage.mean(),
         openp=openo.amount_arr.sum(), cust=int(accounts.is_customer.sum()),
         reps=len(sales), attn=att.attainment_pct.mean())
K["co"]=K["nbb"]/K["tgt"]*100

over    = sales.annual_nbb_quota.sum()/K['tgt']                          # quota over-assignment
reg     = att.groupby("theater").attainment_pct.mean().reindex(["Americas","EMEA","APJ","PubSec"])
geo_att = att.groupby("geo").attainment_pct.mean(); mea_att=geo_att["MEA"]
_oppg   = opps.merge(sales[["rep_id","geo"]], on="rep_id"); _clg=_oppg[_oppg.is_closed]
mea_wr  = _clg[_clg.geo=="MEA"].is_won.mean()*100

# =========================================================== 3. CHARTS ========
def save(fig,name): fig.savefig(ASSET_DIR+name,dpi=130,bbox_inches="tight",facecolor="white"); plt.close(fig)
def b64(name):
    with open(ASSET_DIR+name,"rb") as f: return "data:image/png;base64,"+base64.b64encode(f.read()).decode()

m2q={1:"Q1",2:"Q1",3:"Q1",4:"Q2",5:"Q2",6:"Q2",7:"Q3",8:"Q3",9:"Q3",10:"Q4",11:"Q4",12:"Q4"}
nb["q"]=pd.to_datetime(nb.booking_date).dt.month.map(m2q)
qb=nb.groupby("q").nbb_arr.sum().reindex(["Q1","Q2","Q3","Q4"])/1e6
qt=targets.assign(q=targets.fiscal_quarter.str[-2:]).groupby("q").nbb_target.sum().reindex(["Q1","Q2","Q3","Q4"])/1e6

# 2 · bookings vs target
f,ax=plt.subplots(figsize=(9,4.5)); x=np.arange(4)
ax.bar(x,qb.values,color=NAVY,width=0.6,label="Actual NBB"); ax.plot(x,qt.values,color=ORANGE,marker="o",lw=2,label="Target")
for i,v in enumerate(qb.values): ax.text(i,v+0.6,f"${v:.0f}M",ha="center",fontsize=9)
ax.set_xticks(x); ax.set_xticklabels(["Q1","Q2","Q3","Q4"]); ax.set_ylabel("$M"); ax.set_title("New Business vs Target by Quarter"); ax.legend()
save(f,"bookings.png")

# 3 · funnel + win rate by segment
f,ax=plt.subplots(1,2,figsize=(11,4.5))
order=["Prospecting","Discovery","Proposal","Negotiation"]; sv=openo.groupby("stage").amount_arr.sum().reindex(order)/1e6
ax[0].barh(range(4)[::-1],sv.values,color=TEAL); ax[0].set_yticks(range(4)[::-1]); ax[0].set_yticklabels(order)
for i,v in enumerate(sv.values[::-1]): ax[0].text(v,i,f" ${v:.0f}M",va="center",fontsize=9)
ax[0].set_xlabel("$M open"); ax[0].set_title("Open Pipeline by Stage")
wr=(closed.groupby("segment").is_won.mean()*100).reindex(["Commercial","Mid-Market","Enterprise"])
bb=ax[1].bar(wr.index,wr.values,color=[GREEN,GOLD,ORANGE])
for b,v in zip(bb,wr.values): ax[1].text(b.get_x()+b.get_width()/2,v+0.4,f"{v:.0f}%",ha="center",fontweight="bold")
ax[1].set_ylabel("Win rate %"); ax[1].set_title("Win Rate by Segment"); ax[1].set_ylim(0,max(wr.values)*1.3)
save(f,"funnel.png")

# 4 · forecast
fc=(openo.groupby(["theater","forecast_category"]).weighted.sum().unstack(fill_value=0).reindex(["Americas","EMEA","APJ","PubSec"]))/1e6
f,ax=plt.subplots(figsize=(9,4.5)); bottom=np.zeros(len(fc))
for c,col in zip([x for x in ["Commit","Best Case","Pipeline"] if x in fc],[GREEN,GOLD,SLATE]):
    ax.bar(fc.index,fc[c],bottom=bottom,color=col,label=c); bottom+=fc[c].values
ax.set_ylabel("$M weighted"); ax.set_title("Weighted Pipeline by Forecast Category"); ax.legend(); save(f,"forecast.png")

# 5 · attainment by title
f,ax=plt.subplots(figsize=(9,4.5)); torder=["Commercial AE","Mid-Market AE","Public Sector AE","Enterprise AE","Strategic AE"]
sns.boxplot(data=att,x="rep_title",y="attainment_pct",order=torder,ax=ax,color=LIGHT,width=0.6,fliersize=2)
sns.stripplot(data=att,x="rep_title",y="attainment_pct",order=torder,ax=ax,color=NAVY,size=3,alpha=0.5,jitter=0.25)
ax.axhline(100,ls="--",color=ORANGE); ax.set_xlabel(""); ax.set_ylabel("Attainment %"); ax.set_title("Attainment by Rep Title"); ax.tick_params(axis="x",rotation=20)
save(f,"attain_title.png")

# 5 · attainment by geo (MEA leads, war-driven)
f,ax=plt.subplots(figsize=(9,5))
gm=att.groupby("geo").attainment_pct.mean().sort_values(ascending=False)
ax.barh(range(len(gm))[::-1], gm.values, color=[ORANGE if g=="MEA" else NAVY for g in gm.index])
ax.set_yticks(range(len(gm))[::-1]); ax.set_yticklabels(gm.index)
for i,v in enumerate(gm.values[::-1]): ax.text(v,i,f" {v:.0f}%",va="center",fontsize=8)
ax.axvline(100,ls="--",color=SLATE,lw=.8); ax.set_xlabel("Avg attainment %"); ax.set_title("Rep Attainment by Geo — MEA leads the company")
save(f,"attain_region.png")

# 5 · attainment drivers
drv={"pipeline_coverage":"Pipeline coverage (x)","xdr_support":"# XDRs supporting","partner_sourced_pct":"Partner-sourced %"}
f,ax=plt.subplots(1,3,figsize=(15,4.3))
for a,(c,l) in zip(ax,drv.items()):
    sns.regplot(data=att,x=c,y="attainment_pct",ax=a,scatter_kws=dict(s=18,alpha=0.5,color=SLATE),line_kws=dict(color=ORANGE))
    a.axhline(100,ls="--",color=SLATE,lw=.7); a.set_title(f"{l}  (r={att.attainment_pct.corr(att[c]):+.2f})"); a.set_xlabel(l); a.set_ylabel("Attainment %")
save(f,"drivers.png")

# 6 · territory
f,ax=plt.subplots(1,2,figsize=(12,4.5))
book=accounts[accounts.is_customer].groupby("owner_rep_id").current_arr.sum().rename("book")/1e6
tb=sales.merge(book,left_on="rep_id",right_index=True,how="left").fillna({"book":0})
sns.boxplot(data=tb,x="theater",y="book",order=["Americas","EMEA","APJ","PubSec"],hue="theater",legend=False,palette=THEATER_C,width=0.6,fliersize=2,ax=ax[0])
ax[0].set_title("Customer ARR per Rep ($M)"); ax[0].set_xlabel(""); ax[0].set_ylabel("$M book")
seg=accounts.groupby(["theater","segment"]).size().unstack(fill_value=0).reindex(["Americas","EMEA","APJ","PubSec"])
seg.plot(kind="bar",stacked=True,ax=ax[1],color=[NAVY,TEAL,GOLD,ORANGE][:seg.shape[1]])
ax[1].set_title("Account Universe by Segment"); ax[1].set_xlabel(""); ax[1].set_ylabel("# accounts"); ax[1].tick_params(axis="x",rotation=0)
save(f,"territory.png")

# 7 · capacity
f,ax=plt.subplots(1,2,figsize=(12,4.5))
rc=sales.groupby(["theater","ramp_status"]).size().unstack(fill_value=0).reindex(["Americas","EMEA","APJ","PubSec"])
rc=rc[[c for c in ["Ramped","Ramping"] if c in rc]]; rc.plot(kind="bar",stacked=True,ax=ax[0],color=[TEAL,GOLD])
ax[0].set_title("Headcount by Ramp Status"); ax[0].set_ylabel("# reps"); ax[0].set_xlabel(""); ax[0].tick_params(axis="x",rotation=0)
sns.histplot(sales.pipeline_coverage,bins=20,ax=ax[1],color=NAVY); ax[1].axvline(3,ls="--",color=ORANGE,label="3x benchmark")
ax[1].set_title("Pipeline Coverage Distribution"); ax[1].set_xlabel("coverage (x)"); ax[1].legend()
save(f,"capacity.png")

# 8 · product x geo
f,ax=plt.subplots(figsize=(8.5,4.5)); m=fact.merge(sales[["rep_id","theater"]],on="rep_id")
piv=(m.pivot_table(index="product_type",columns="theater",values="nbb_arr",aggfunc="sum")/1e6).reindex(index=["SaaS","Term","Maintenance","Services","TAM"],columns=["Americas","EMEA","APJ","PubSec"])
sns.heatmap(piv,annot=True,fmt=".0f",cmap="BuGn",ax=ax,cbar_kws={"label":"$M"},linewidths=.5)
ax.set_title("Total Bookings: Product Type x Geo ($M)"); ax.set_xlabel(""); ax.set_ylabel(""); save(f,"prodgeo.png")
print("section charts rendered")

# =========================================================== 4. DASHBOARD =====
def build_dashboard():
    fig=plt.figure(figsize=(20,15),facecolor="white")
    gs=gridspec.GridSpec(4,3,height_ratios=[0.5,1,1,1],hspace=0.42,wspace=0.24,left=0.05,right=0.97,top=0.90,bottom=0.05)
    fig.suptitle("GTM Operating Review — FY2026",x=0.05,y=0.965,ha="left",fontsize=24,fontweight="bold",color=NAVY)
    fig.text(0.05,0.925,"OGN Security  ·  New Business, Renewals & Expansion  ·  synthetic data for portfolio demo",ha="left",fontsize=12,color=SLATE)
    fig.text(0.97,0.955,f"Refreshed: {datetime.date.today():%b %d, %Y}",ha="right",fontsize=11,color=SLATE)
    fig.text(0.97,0.93,"CRO: Idris E",ha="right",fontsize=11,color=SLATE)
    kpis=[("New Business",f"${K['nbb']/1e6:.0f}M",f"{K['co']:.0f}% of ${K['tgt']/1e6:.0f}M target",NAVY),
          ("Attainment",f"{K['co']:.0f}%",f"to target · reps avg {K['attn']:.0f}%",TEAL if K['co']>=100 else ORANGE),
          ("Win Rate",f"{K['win']:.0f}%","New Business opps",GOLD),
          ("Pipeline Coverage",f"{K['cov']:.1f}x","avg open / quota",TEAL),
          ("Open Pipeline",f"${K['openp']/1e6:.0f}M","FY27 close",SLATE),
          ("Customers",f"{K['cust']:,}","of 4,000 accounts",GREEN)]
    kg=gridspec.GridSpecFromSubplotSpec(1,6,subplot_spec=gs[0,:],wspace=0.15)
    for i,(lab,val,sub,c) in enumerate(kpis):
        ax=fig.add_subplot(kg[0,i]); ax.axis("off")
        ax.add_patch(plt.Rectangle((0,0),1,1,transform=ax.transAxes,facecolor=LIGHT,edgecolor=c,linewidth=2))
        ax.text(0.5,0.72,val,ha="center",va="center",fontsize=24,fontweight="bold",color=c,transform=ax.transAxes)
        ax.text(0.5,0.40,lab,ha="center",va="center",fontsize=11,fontweight="bold",color=NAVY,transform=ax.transAxes)
        ax.text(0.5,0.18,sub,ha="center",va="center",fontsize=8.5,color=SLATE,transform=ax.transAxes)
    a1=fig.add_subplot(gs[1,0]); xx=np.arange(4)
    a1.bar(xx,qb.values,color=NAVY,width=0.6,label="Actual"); a1.plot(xx,qt.values,color=ORANGE,marker="o",lw=2,label="Target")
    a1.set_xticks(xx); a1.set_xticklabels(["Q1","Q2","Q3","Q4"]); a1.set_ylabel("$M"); a1.set_title("New Business vs Target by Quarter"); a1.legend(fontsize=8)
    a2=fig.add_subplot(gs[1,1]); sv2=openo.groupby("stage").amount_arr.sum().reindex(order)/1e6
    a2.barh(range(4)[::-1],sv2.values,color=TEAL); a2.set_yticks(range(4)[::-1]); a2.set_yticklabels(order)
    for i,v in enumerate(sv2.values[::-1]): a2.text(v,i,f" ${v:.0f}M",va="center",fontsize=9)
    a2.set_xlabel("$M open"); a2.set_title("Open Pipeline by Stage")
    a3=fig.add_subplot(gs[1,2]); wr3=(closed.groupby("segment").is_won.mean()*100).reindex(["Commercial","Mid-Market","Enterprise"])
    b3=a3.bar(wr3.index,wr3.values,color=[GREEN,GOLD,ORANGE])
    for b,v in zip(b3,wr3.values): a3.text(b.get_x()+b.get_width()/2,v+0.5,f"{v:.0f}%",ha="center",fontsize=9,fontweight="bold")
    a3.set_ylabel("Win rate %"); a3.set_title("Win Rate by Segment"); a3.set_ylim(0,max(wr3.values)*1.25)
    a4=fig.add_subplot(gs[2,0]); gmd=att.groupby("geo").attainment_pct.mean().sort_values(ascending=False)
    a4.barh(range(len(gmd))[::-1],gmd.values,color=[ORANGE if g=="MEA" else NAVY for g in gmd.index])
    a4.set_yticks(range(len(gmd))[::-1]); a4.set_yticklabels(gmd.index,fontsize=7.5); a4.axvline(100,ls="--",color=SLATE,lw=.8)
    a4.set_xlabel("Avg attainment %"); a4.set_title("Attainment by Geo — MEA leads (war-driven)")
    a5=fig.add_subplot(gs[2,1]); mm=fact.merge(sales[["rep_id","theater"]],on="rep_id")
    p5=(mm.pivot_table(index="product_type",columns="theater",values="nbb_arr",aggfunc="sum")/1e6).reindex(index=["SaaS","Term","Maintenance","Services","TAM"],columns=["Americas","EMEA","APJ","PubSec"])
    sns.heatmap(p5,annot=True,fmt=".0f",cmap="BuGn",ax=a5,cbar_kws={"label":"$M"},linewidths=.5)
    a5.set_title("Bookings: Product Type × Geo ($M)"); a5.set_xlabel(""); a5.set_ylabel("")
    a6=fig.add_subplot(gs[2,2])
    sns.regplot(data=att,x="pipeline_coverage",y="attainment_pct",ax=a6,scatter_kws=dict(s=22,alpha=0.5,color=SLATE),line_kws=dict(color=ORANGE))
    a6.axhline(100,ls="--",color=SLATE,lw=.8); a6.set_title(f"Attainment vs Pipeline Coverage (r={att.attainment_pct.corr(att.pipeline_coverage):+.2f})")
    a6.set_xlabel("Pipeline coverage (x)"); a6.set_ylabel("Attainment %")
    a7=fig.add_subplot(gs[3,0]); bk=accounts[accounts.is_customer].groupby("owner_rep_id").current_arr.sum().rename("book")/1e6
    t7=sales.merge(bk,left_on="rep_id",right_index=True,how="left").fillna({"book":0})
    sns.boxplot(data=t7,x="theater",y="book",order=["Americas","EMEA","APJ","PubSec"],hue="theater",legend=False,palette=THEATER_C,width=0.6,fliersize=2,ax=a7)
    a7.set_title("Territory Balance: Customer ARR / Rep ($M)"); a7.set_xlabel(""); a7.set_ylabel("$M book")
    a8=fig.add_subplot(gs[3,1]); rc8=sales.groupby(["theater","ramp_status"]).size().unstack(fill_value=0).reindex(["Americas","EMEA","APJ","PubSec"])
    bottom=np.zeros(len(rc8))
    for col,c in zip([x for x in ["Ramped","Ramping"] if x in rc8],[TEAL,GOLD]):
        a8.bar(rc8.index,rc8[col],bottom=bottom,color=c,label=col); bottom+=rc8[col].values
    a8.set_title("Sales Capacity: Headcount by Ramp Status"); a8.set_ylabel("# reps"); a8.legend(fontsize=8)
    a9=fig.add_subplot(gs[3,2]); fc9=(openo.groupby(["theater","forecast_category"]).weighted.sum().unstack(fill_value=0).reindex(["Americas","EMEA","APJ","PubSec"]))/1e6
    bottom=np.zeros(len(fc9))
    for c,col in zip([x for x in ["Commit","Best Case","Pipeline"] if x in fc9],[GREEN,GOLD,SLATE]):
        a9.bar(fc9.index,fc9[c],bottom=bottom,color=col,label=c); bottom+=fc9[c].values
    a9.set_title("Weighted Pipeline by Forecast Category ($M)"); a9.set_ylabel("$M weighted"); a9.legend(fontsize=8)
    fig.savefig(OUT_FOLDER+"gtm_dashboard.png",dpi=110,bbox_inches="tight",facecolor="white"); plt.close(fig)
build_dashboard()
print("dashboard saved ->", OUT_FOLDER+"gtm_dashboard.png")

# =========================================================== 5. TABLES ========
def rows(df): return "".join("<tr>"+"".join(f"<td>{c}</td>" for c in r)+"</tr>" for r in df.itertuples(index=False))
kpi_tbl=pd.DataFrame({"Metric":["New Business","NBB Target","Company Attainment","Renewals","Expansion","Win Rate (NB)","Avg Pipeline Coverage","Open Pipeline","Reps","Avg Rep Attainment"],
    "Value":[f"${K['nbb']/1e6:.0f}M",f"${K['tgt']/1e6:.0f}M",f"{K['co']:.0f}%",f"${K['ren']/1e6:.0f}M",f"${K['exp']/1e6:.0f}M",f"{K['win']:.0f}%",f"{K['cov']:.1f}x",f"${K['openp']/1e6:.0f}M",f"{K['reps']}",f"{K['attn']:.0f}%"]})
wseg=closed.groupby("segment").agg(opps=("opp_id","count"),won=("is_won","sum")).reset_index()
wseg["win_rate"]=(wseg.won/wseg.opps*100).round(0).astype(int).astype(str)+"%"
_dc=att.rep_id.map(nb.groupby('rep_id').size()).fillna(0)
drv_tbl=pd.DataFrame({"Driver":["Pipeline coverage","XDR support","Partner-sourced %","Rep tenure (months)","# Deals closed"],
    "r":[f"{att.attainment_pct.corr(att.pipeline_coverage):+.2f}",f"{att.attainment_pct.corr(att.xdr_support):+.2f}",
         f"{att.attainment_pct.corr(att.partner_sourced_pct):+.2f}",f"{att.attainment_pct.corr(att.tenure_months):+.2f}",f"{att.attainment_pct.corr(_dc):+.2f}"]})

# =========================================================== 6. HTML REPORT ===
CSS = """
@page { size: Letter; margin: 20mm 18mm; }
* { box-sizing: border-box; }
body { font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif; color:#1A1A1A; font-size:11.2pt; line-height:1.5; }
h2 { color:#1F3A5F; font-size:15.5pt; border-bottom:2px solid #2A9D8F; padding-bottom:4px; margin:0 0 10px; }
h3 { color:#B4512A; font-size:12pt; margin:14px 0 4px; }
p { margin:0 0 9px; }
.section { page-break-before: always; }
.lead { color:#6B7A8F; font-size:12pt; }
img { max-width:100%; display:block; margin:12px auto; border:1px solid #E2E8F0; border-radius:4px; }
table.tbl { border-collapse:collapse; width:100%; margin:10px 0 14px; font-size:10pt; }
table.tbl th { background:#1F3A5F; color:#fff; text-align:left; padding:6px 9px; }
table.tbl td { border-bottom:1px solid #E2E8F0; padding:5px 9px; }
table.tbl tr:nth-child(even) td { background:#F7FAFC; }
.kpis { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }
.kpi { flex:1 1 30%; background:#EEF2F6; border-left:4px solid #2A9D8F; padding:8px 12px; border-radius:4px; }
.kpi .v { font-size:17pt; font-weight:700; color:#1F3A5F; } .kpi .l { font-size:9pt; color:#6B7A8F; }
.callout { background:#FDF6E3; border-left:4px solid #E9C46A; padding:10px 14px; border-radius:4px; margin:12px 0; }
.rec { background:#F0F7F0; border-left:4px solid #2F6B2F; padding:10px 14px; border-radius:4px; margin:10px 0; }
.cover { height:235mm; display:flex; flex-direction:column; justify-content:center; }
.cover .big { font-size:34pt; color:#1F3A5F; font-weight:800; line-height:1.1; }
.muted { color:#6B7A8F; } ul { margin:4px 0 12px; } li { margin:3px 0; }
"""
def kpi(v,l): return f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>'
enW=closed[closed.segment=='Enterprise'].is_won.mean()*100
coW=closed[closed.segment=='Commercial'].is_won.mean()*100
mmW=closed[closed.segment=='Mid-Market'].is_won.mean()*100

html=f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div class="cover">
  <div class="muted" style="font-size:12pt;letter-spacing:2px;">REVENUE OPERATIONS · PORTFOLIO CASE STUDY</div>
  <div class="big">GTM Operating Review<br>& Revenue Analytics</div>
  <div style="font-size:15pt;color:#2A9D8F;margin-top:10px;">OGN Security — FY2026 Go-To-Market Performance</div>
  <p class="muted" style="margin-top:22px;max-width:150mm;">A full-funnel analysis of a $750M ARR enterprise security-SaaS business:
  bookings and attainment, pipeline and forecast, territory and capacity, and the drivers of rep performance — built end-to-end in Python
  from a relational Salesforce-style data model.</p>
  <div style="margin-top:30px;" class="muted">Prepared by <b>Idris E</b> · {datetime.date.today():%B %Y} · Synthetic data for demonstration</div>
</div>

<div class="section"><h2>Executive Summary</h2>
<p class="lead">The business closed FY2026 at <b>${K['nbb']/1e6:.0f}M of New Business against a ${K['tgt']/1e6:.0f}M target ({K['co']:.0f}% attainment)</b>,
on a {K['reps']}-seller global organization, with ${K['ren']/1e6:.0f}M in renewals and ${K['exp']/1e6:.0f}M in expansion on top. Underneath that hit
plan the <b>average rep attained {K['attn']:.0f}% of quota</b> — the book is over-assigned at {over:.2f}x target — and attainment varied sharply by
geography, with the <b>MEA territory the top performer at ~{mea_att:.0f}%</b> on war-driven demand even as Public Sector trailed near ~{reg['PubSec']:.0f}%.</p>
<div class="kpis">
{kpi(f"${K['nbb']/1e6:.0f}M","New Business")}{kpi(f"{K['co']:.0f}%","Attainment to target")}{kpi(f"{K['win']:.0f}%","New-Business win rate")}
{kpi(f"{K['cov']:.1f}x","Avg pipeline coverage")}{kpi(f"${K['openp']/1e6:.0f}M","Open pipeline")}{kpi(f"{K['cust']:,}","Active customers")}
</div>
<p>Three findings define the year. First, <b>pipeline coverage is the strongest, most actionable driver of attainment</b>
(r = {att.attainment_pct.corr(att.pipeline_coverage):+.2f}): reps with 4–6x coverage reliably beat plan, thin-coverage reps are the leading indicator
of a miss. Second, <b>win rates diverge by segment</b> — Commercial {coW:.0f}% vs Enterprise {enW:.0f}% — a qualification problem at the top of the
market. Third, <b>the book is concentrated in SaaS and the Americas</b>, healthy for ARR quality but leaving whitespace in EMEA/APJ and the non-SaaS lines.</p>
</div>

<div class="section"><h2>1 · Business Context & Data Model</h2>
<p>OGN Security is a (synthetic) global enterprise security-SaaS company with ~<b>$750M ARR</b>. The analysis uses a relational model mirroring a
Salesforce + planning stack: a bookings fact table joined to dimensions for accounts, product, geography, and the sales org. Four theaters
(Americas, EMEA, APJ, Public Sector), a six-level hierarchy from CRO to AE, five seller titles, fifteen product families sold as SaaS / Term /
Maintenance / Services / TAM, and bookings split into New / Renewal / Expansion so the New-Business engine can be measured on its own.</p>
<table class="tbl"><tr><th>Table</th><th>Grain</th><th>Role</th></tr>
<tr><td>fact_bookings</td><td>one row per booked deal</td><td>New / Renewal / Expansion revenue</td></tr>
<tr><td>opportunities</td><td>one row per New-Business opp</td><td>pipeline, stage, win/loss, forecast</td></tr>
<tr><td>accounts</td><td>one row per account</td><td>segment, industry, ARR, territory owner</td></tr>
<tr><td>dim_sales_org</td><td>one row per rep</td><td>hierarchy, quota, coverage, ramp, XDR, partner</td></tr>
<tr><td>targets</td><td>theater × quarter</td><td>NBB plan</td></tr></table></div>

<div class="section"><h2>2 · GTM Operating Cadence & Attainment</h2>
<p>The cadence opens on New Business booked against plan: <b>{K['co']:.0f}% of the ${K['tgt']/1e6:.0f}M target</b>, building through the year as the
plan back-loads to Q4. This actual-vs-target view is the backbone of the weekly pipeline review and the QBR.</p>
<img src="{b64('bookings.png')}">
<table class="tbl"><tr><th>Metric</th><th>Value</th></tr>{rows(kpi_tbl)}</table></div>

<div class="section"><h2>3 · Funnel Performance & Win/Loss</h2>
<p>Open New-Business pipeline totals <b>${K['openp']/1e6:.0f}M</b>, weighted to the early stages — healthy for future quarters but to be discounted
heavily in any forecast. The revealing cut is win rate by segment: Commercial {coW:.0f}%, Mid-Market {mmW:.0f}%, Enterprise {enW:.0f}%. A declining
win rate as deals grow is expected, but a gap this wide warrants a structured win/loss program.</p>
<img src="{b64('funnel.png')}">
<table class="tbl"><tr><th>Segment</th><th>Closed opps</th><th>Won</th><th>Win rate</th></tr>{rows(wseg[['segment','opps','won','win_rate']])}</table></div>

<div class="section"><h2>4 · Sales Forecasting</h2>
<p>Bottoms-up: each open opportunity is weighted by its stage probability and rolled up by forecast category (Commit / Best Case / Pipeline) per
theater, separating the high-confidence call from the upside. The discipline this enforces is coverage-to-target, and the weekly review tracks
category movement — deals sliding from Commit to Best Case are the earliest warning of a miss.</p>
<img src="{b64('forecast.png')}"></div>

<div class="section"><h2>5 · Rep Performance & Attainment Drivers</h2>
<p>The year's key nuance: the company hit <b>{K['co']:.0f}% of target</b>, yet the <b>average seller attained {K['attn']:.0f}% of quota</b> — the
signature of an over-assigned plan ({over:.2f}x target). A healthy business hits its number while most reps sit below 100%, which is why company
attainment is never reported without the rep-level distribution.</p>
<p>That distribution follows a <b>geographic curve, and the standout runs against intuition</b>: the single highest-attaining geo is
<b>MEA at ~{mea_att:.0f}%</b> — above every Americas territory — on war-driven urgency that lands marketing with less friction and lifts the
<b>MEA win rate to ~{mea_wr:.0f}% vs ~{K['win']:.0f}% company-wide</b>. Macro conditions, not just rep skill, move a territory's number — and a geo
running hot for exogenous reasons should not have its quotas permanently reset off a spike that may reverse.</p>
<img src="{b64('attain_region.png')}">
<img src="{b64('attain_title.png')}">
<p>Regressing attainment against candidate drivers produces a clear hierarchy.</p>
<img src="{b64('drivers.png')}">
<table class="tbl"><tr><th>Driver</th><th>Correlation with attainment (r)</th></tr>{rows(drv_tbl)}</table>
<div class="callout"><b>Pipeline coverage is the dominant lever (r = {att.attainment_pct.corr(att.pipeline_coverage):+.2f}).</b> XDR support is second,
partner-sourcing third; raw deal count shows no relationship. The null results make the finding credible — signal, not artifact.</div></div>

<div class="section"><h2>6 · Territory & Segment Model</h2>
<p>Territory design is where coverage is won or lost before the quarter starts. Americas reps carry the largest and most variable books; uneven
load is a quiet tax on attainment. A disciplined carve balances account potential, not just count.</p>
<img src="{b64('territory.png')}"></div>

<div class="section"><h2>7 · Capacity, Coverage & Quota</h2>
<p>Of {K['reps']} sellers, {int((sales.ramp_status=='Ramping').sum())} are ramping and {int((sales.ramp_status=='Ramped').sum())} fully productive.
Total carried quota of ${sales.annual_nbb_quota.sum()/1e6:.0f}M on a ${K['tgt']/1e6:.0f}M target is ~{over:.2f}x over-assignment — the buffer that
absorbs ramp and attrition. The capacity model answers: how many productive heads are needed, and when must they be hired to ramp in time?</p>
<img src="{b64('capacity.png')}"></div>

<div class="section"><h2>8 · Strategic Analysis: Product × Geo</h2>
<p>What sells where: the book is dominated by SaaS and the Americas. EMEA and APJ run below the Americas across every product type, and the
non-SaaS lines are thin — each a plannable coverage or packaging decision rather than a default.</p>
<img src="{b64('prodgeo.png')}"></div>

<div class="section"><h2>9 · Findings & Recommendations</h2>
<h3>What's working</h3>
<ul><li>Company hit <b>{K['co']:.0f}% of target</b>; the Americas carries the org at ~{reg['Americas']:.0f}% attainment.</li>
<li><b>Pipeline coverage predicts attainment</b> — the most coachable lever.</li>
<li>ARR quality is high: <b>SaaS-led</b>, with ${K['ren']/1e6:.0f}M of renewals as a durable base.</li></ul>
<h3>Where to focus</h3>
<div class="rec"><b>1 · Fix Enterprise win rate</b> (~{enW:.0f}% vs ~{coW:.0f}% Commercial): structured win/loss + tighter qualification.</div>
<div class="rec"><b>2 · Enforce a 3x coverage floor</b> in the weekly cadence; back-fill thin reps with XDR and partner sourcing.</div>
<div class="rec"><b>3 · Set quotas to the geographic curve — treat MEA's surge (~{mea_att:.0f}%, ~{mea_wr:.0f}% win) as exogenous</b> and don't permanently
re-base it; re-examine Strategic AE quotas.</div>
<div class="rec"><b>4 · Rebalance the Americas carve</b> to even load and protect coverage.</div>
<div class="rec"><b>5 · Make a deliberate EMEA/APJ & non-SaaS whitespace decision</b> in annual planning.</div>
<h3>Next analytical step</h3>
<p>Add <b>time-phased pipeline snapshots</b> to measure forecast accuracy and pipeline velocity across the quarter.</p></div>

<div class="section"><h2>Appendix · Methodology</h2>
<p>Computed in Python (pandas, seaborn, matplotlib) from the relational model in Section 1. Attainment = rep New-Business ARR ÷ annual quota;
win rate = closed-won ÷ all closed New-Business opps; forecast weights each open opp by stage probability; correlations are Pearson. Data is
synthetic and seeded; designed relationships (e.g. coverage→attainment, MEA uplift) demonstrate the analysis. This pipeline is fully refreshable.</p>
<p class="muted">Synthetic data · OGN Security is a fictional company created for this portfolio case study.</p></div>
</body></html>"""

html_path=OUT_FOLDER+"GTM_Revenue_Analytics_Report.html"
open(html_path,"w").write(html)
print("HTML report written ->", html_path)

# =========================================================== 7. RENDER PDF ====
pdf_path=OUT_FOLDER+"GTM_Revenue_Analytics_Report.pdf"
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br=p.chromium.launch(); pg=br.new_page()
        pg.goto("file://"+os.path.abspath(html_path)); pg.wait_for_timeout(500)
        pg.pdf(path=pdf_path, format="Letter", print_background=True,
               margin={"top":"14mm","bottom":"16mm","left":"14mm","right":"14mm"},
               display_header_footer=True, header_template="<div></div>",
               footer_template='<div style="width:100%;font-size:8px;color:#6B7A8F;padding:0 14mm;display:flex;justify-content:space-between;">'
                               '<span>GTM Operating Review · OGN Security · Idris E</span>'
                               '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')
        br.close()
    print("PDF written ->", pdf_path)
except Exception as e:
    print("\n[Playwright not available — PDF step skipped]")
    print("  reason:", e)
    print(f"  To get the PDF: open {html_path} in a browser and choose Print -> Save as PDF,")
    print("  or install Playwright once:  pip install playwright && playwright install chromium")

print("\nDONE. Outputs in:", OUT_FOLDER)
