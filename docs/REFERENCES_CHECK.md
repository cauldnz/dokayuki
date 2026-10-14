# Reference check

Rule (spec update 1 §4): no reference appears on the site unless it is verified here: the DOI
resolves, the bibliographic data match, and the cited claim appears in the source. "partial" means
the DOI and metadata are verified (Crossref) but the claim was confirmed only from the abstract or a
secondary source because the full text was paywalled from the build container. Entries marked
**no** or **UNVERIFIED** are kept in `references.bib` for the record but are **excluded from the
site** by `dokayuki.site.references` (status column is what it reads). Check performed 2026-10-14 via
Crossref, doi.org, OpenAlex/Semantic Scholar abstracts, J-STAGE, arXiv, NSF-PAR and PMC full texts.

| key | citation | DOI | claim it supports | status | checked | notes |
|---|---|---|---|---|---|---|
| guan2026advancing | Guan, Mouatadid et al. 2026, arXiv 2604.16238 v3 | 10.48550/arXiv.2604.16238 | PBC = Debias++ and Persistence++ applied in parallel; improves ECMWF T2m, precipitation and MSLP at weeks 3–4; absolute RPSS of order 0.1 or less | yes (preprint) | arXiv full text | **The Nature DOI 10.1038/s41586-026-11126-x in the brief does not resolve (doi.org and Crossref 404, no trace online). Cite the preprint until it does.** Full text: PBC boosts debiased-ECMWF T and SLP RPSS by 26–37 % / 16–32 % over baselines of 0.07–0.10 / 0.06–0.11 |
| mouatadid2023adaptive | Mouatadid et al. 2023, Nat. Commun. 14, 3482 | 10.1038/s41467-023-38874-y | ABC corrects ECMWF/SubX/CFSv2 biases, improving weeks 3–4 and 5–6 skill | yes | PMC full text | CONUS domain |
| steenburgh2020perspectives | Steenburgh & Nakai 2020, BAMS 101, E58 | 10.1175/BAMS-D-18-0335.1 | Sea-of-Japan sea-effect regime: ~850 km NW fetch vs ~400 km Lake Superior, JPCZ from flow interaction with the Korean Highlands and differential heating, deeper systems than the Great Lakes | yes | NSF-PAR full text | "strong instability" not verbatim; say "deeper systems and longer fetch" |
| steenburgh2000climatology | Steenburgh, Halvorson & Onton 2000, MWR 128, 709 | 10.1175/1520-0493(2000)128<0709:COLESO>2.0.CO;2 | Great Salt Lake lake-effect: lake minus **700 hPa** temperature difference exceeded 16 °C (≈ dry-adiabatic) | yes, claim corrected | abstract | **The brief's "850 hPa" was wrong; it is 700 hPa** |
| niziol1987operational | Niziol 1987, Wea. Forecasting 2, 310 | 10.1175/1520-0434(1987)002<0310:OFOLES>2.0.CO;2 | lake-to-850 hPa difference ≥ 13 °C as a lake-effect criterion | partial | Crossref + NWS ER Tech. Attachment 2000-05 citing Niziol and Holroyd (1971) | AMS full text paywalled; worded on the site as "the 13 °C guideline attributed to Holroyd (1971) and Niziol (1987)" |
| veals2015climatological | Veals & Steenburgh 2015, MWR 143, 3591 | 10.1175/MWR-D-15-0009.1 | orographic enhancement of lake-effect precipitation over Tug Hill | yes | abstract | |
| nagata1986formation | Nagata et al. 1986, JMSJ 64, 841 | 10.2151/jmsj1965.64.6_841 | JPCZ: land–sea thermal contrast leads, blocking by the mountains north of Korea intensifies the convergence | partial | J-STAGE abstract | journal is JMSJ (the brief said MWR) |
| nagata1991further | Nagata 1991, JMSJ 69, 419 | 10.2151/jmsj1965.69.3_419 | same, three forcings of comparable importance | partial | J-STAGE abstract | |
| west2022formation | West & Steenburgh 2022, MWR 150, 157 | 10.1175/MWR-D-21-0095.1 | JPCZ forms downstream of the Korean Highlands (Changbai/Jangbaek) | yes | NSF-PAR full text | used instead of Asai 1988 |
| asai1988mesoscale | Asai 1988, Tenki 35, 156 (Japanese) | none | JPCZ mesoscale features | UNVERIFIED | PDF exists at metsoc.jp; text not checked | excluded from the site |
| baldwin2001stratospheric | Baldwin & Dunkerton 2001, Science 294, 581 | 10.1126/science.1063315 | after weak-vortex events the 60-day mean surface pressure resembles the AO pattern | yes | abstract | |
| kretschmer2018more | Kretschmer et al. 2018, BAMS 99, 49 | 10.1175/BAMS-D-16-0259.1 | persistent weak vortex states linked to cold extremes in midlatitude Eurasia | partial | abstract | North America not in abstract; site says Eurasia only |
| cohen2014recent | Cohen et al. 2014, Nat. Geosci. 7, 627 | 10.1038/ngeo2234 | review of pathways from Arctic amplification to midlatitude extremes, with large uncertainty | yes | abstract | |
| cohen2021linking | Cohen et al. 2021, Science 373, 1116 | 10.1126/science.abi9167 | stretched polar vortex linked to extreme cold in parts of Asia and North America | yes | abstract | |
| domeisen2020role1 | Domeisen et al. 2020, JGR-A 125, e2019JD030920 | 10.1029/2019JD030920 | stratospheric predictability; high-top systems do better | yes | abstract | |
| domeisen2020role2 | Domeisen et al. 2020, JGR-A 125, e2019JD030923 | 10.1029/2019JD030923 | surface predictability rises after weak-vortex events | yes | abstract | |
| mariotti2020windows | Mariotti et al. 2020, BAMS 101, E608 | 10.1175/BAMS-D-18-0326.1 | windows of opportunity | yes | abstract | |
| gong2002siberian | Gong & Ho 2002, Theor. Appl. Climatol. 72, 1 | 10.1007/s007040200008 | Siberian High central intensity vs Asian winter temperature (r = −0.58) | yes (box not stated) | abstract | not the source of our box |
| panagiotopoulos2005observed | Panagiotopoulos et al. 2005, J. Climate 18, 1411 | 10.1175/JCLI3352.1 | SHI = DJF SLP over 40–65°N, 80–120°E; trend −2.5 hPa/decade 1978–2001 | partial | abstract + D'Arrigo et al. 2005 (co-authored) | full text paywalled |
| hanawa1988surface | Hanawa et al. 1988, JMSJ 66, 445 | 10.2151/jmsj1965.66.3_445 | MOI = SLP difference Nemuro–Irkutsk (operative sign Irkutsk − Nemuro, high = cold Japan), attributed by the authors to Watanabe & Hanawa | yes | J-STAGE full text | cite as "following Hanawa et al. (1988)" |
| jhun2004new | Jhun & Lee 2004, J. Climate 17, 711 | 10.1175/1520-0442(2004)017<0711:ANEAWM>2.0.CO;2 | EAWM index = U300(27.5–37.5°N, 110–170°E) − U300(50–60°N, 80–140°E) | partial | via Wang & Chen 2010 Table 1 | |
| trenberth1994decadal | Trenberth & Hurrell 1994, Clim. Dyn. 9, 303 | 10.1007/BF00204745 | NPI region 30–65°N, 160°E–140°W | partial | abstract + NCAR Climate Data Guide | |
| wang2010how | Wang & Chen 2010, Adv. Atmos. Sci. 27, 855 | 10.1007/s00376-009-9094-3 | EAT index of Sun & Li (1997): Φ500 over 30–45°N, 125–145°E; station-pair indices miss the post-1986 weakening | yes | full text | |
| sun1997 | Sun & Li 1997, Chin. Sci. Bull. 42, 500 | none found | EAT index | UNVERIFIED (indirect) | only via Wang & Chen 2010 | cited through Wang & Chen only |
| cheung2013observational | Cheung et al. 2013, Clim. Dyn. 41, 63 | 10.1007/s00382-012-1587-6 | Ural–Siberian blocking (centred 30–100°E) links to the Siberian High; its decay precedes East Asian cold-air outbreaks | yes (claim), box not confirmed | abstract | **our UBI box 45–70°N, 40–80°E is not quoted as theirs; it is marked provisional** |
| luo2016impact1 | Luo et al. 2016, J. Climate 29, 3925 | 10.1175/JCLI-D-15-0611.1 | Ural blocking + Barents–Kara ice loss → warm Arctic, cold Eurasia | partial | abstract | index box unconfirmed |
| peings2019ural | Peings 2019, GRL 46, 5460 | 10.1029/2019GL082097 | November Ural blocking → stratospheric warming and −NAO | partial | abstract | index box unconfirmed |
| west2019characteristics | West, Steenburgh & Mace 2019, JGR-A 124, 1322 | 10.1029/2018JD029586 | sea-effect periods with SST − T850 ≥ 13 °C carry most Sea-of-Japan cloud and precipitation | yes | abstract | |
| weigel2007discrete | Weigel et al. 2007, MWR 135, 118 | 10.1175/MWR3280.1 | RPSS definition; negative bias for small ensembles; debiased RPSSD | yes | abstract | |
| politis1994stationary | Politis & Romano 1994, JASA 89, 1303 | 10.1080/01621459.1994.10476870 | stationary (block) bootstrap for dependent data | yes | abstract | |
| delsole2014comparing | DelSole & Tippett 2014, MWR 142, 4658 | 10.1175/MWR-D-14-00045.1 | tests for comparing two forecasts' skill | yes | abstract | |
| white2000reality | White 2000, Econometrica 68, 1097 | 10.1111/1468-0262.00152 | reality check for data snooping | yes | abstract | |
| hansen2005test | Hansen 2005, JBES 23, 365 | 10.1198/073500105000000063 | test for superior predictive ability | yes | abstract | |
| thompson1998arctic | Thompson & Wallace 1998, GRL 25, 1297 | 10.1029/98GL00950 | AO = leading EOF of NH wintertime SLP; CPC's daily index projects 1000 hPa height poleward of 20°N | partial | abstract + CPC page | |
| takahashi2013impact | Takahashi & Idenaga 2013, JMSJ 91, 639 | 10.2151/jmsj.2013-506 | pressure-gradient (Akita − Nagasaki) index tracks Japan-Sea-side precipitation; MOI weak on short timescales | yes | full text | |
| takano2008influences | Takano, Tachibana & Iwamoto 2008, SOLA 4, 113 | 10.2151/sola.2008-029 | December Sea-of-Japan convective activity tied to air-mass modification and late-autumn local SST | yes | abstract | |

Gaps: AMS and Wiley full texts were unreachable from the build container, so several entries are
"partial"; they are shown on the site with the claim worded at abstract level. Re-check when a
machine with journal access is available.
