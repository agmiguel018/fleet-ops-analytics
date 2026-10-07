# Decision memo — Should Vemov buy a third vehicle now?

**To:** Owner, Vemov · **From:** Operations analytics · **Date:** October 2026
**Data:** money-indexed, so the memo uses ratios and months only · V01 1 Jul – 4 Oct 2026 (96 days, 1,058 trips) · V02 17 Aug – 22 Sep 2026 (36 days, two drivers, two platforms)

## Recommendation
**Not yet.** First make the two existing vehicles work every working day, then buy the third vehicle once availability holds above 90% for two consecutive months.

## Why
| | Today (V01) | Target |
|---|---|---|
| Availability (worked days ÷ working days) | **76.5%** | > 90% |
| Revenue lost on idle working days | **~31%** of the revenue actually earned (96 days) | — |
| Monthly margin, before insurance and taxes | 100 (base) | **~147** with no lost days |
| Payback of a new vehicle at V02's price | **~19 months** | **~12–13 months** |

Every lost working day came from **people or the service phone**: a driver absent, no driver between contracts, or no mobile network. None was mechanical. A third vehicle would add exposure to the same risks.

## Actions, in order
| # | Action | Cost | Expected effect |
|---|---|---|---|
| 1 | **Standby driver** shared by the fleet, paid per day worked | Daily rate only when used | Recovers most of the lost revenue (~31% of actual revenue) |
| 2 | **Second SIM** from another network in each service phone | ~ one SIM per phone | Removes network-outage days |
| 3 | **Weekly GPS-vs-app reconciliation** of kilometres | None: GPS is already installed | Explains the ~1,700 km driven without revenue |
| 4 | **Enforce the 05:30 start**: the 06:00 hour pays the best ticket (+28%) | None | ~8% more revenue per working day |
| 5 | **Quote engine oil** with a second supplier: oil is ~75% of each 7,000 km service | None | Maintenance costs ~78% as much as fuel per km |

## Risks to resolve in parallel
- **Insurance.** Confirm in writing that both vehicles are covered for paid passenger transport; V01's margin is shown before insurance.
- **Receipts.** Washes, parking and two services have no receipts. Always request the company tax number on every purchase.

*Full analysis: [`notebooks/02_analysis.ipynb`](../notebooks/02_analysis.ipynb).*
