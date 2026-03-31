"""
Scraper de datos de selecciones nacionales UEFA.
Consolida datos de:
  - UEFA Nations League 2024-25 (Ligas A, B, C, D)
  - FIFA World Cup 2026 Qualifiers UEFA (Grupos A-L + playoffs)
  - Datos existentes de la API (team_stats.json / data_matches.json)

Fuente: Wikipedia (HTML scrapeado via WebFetch, datos ya extraídos)
"""

import json
import os
from collections import defaultdict
from datetime import datetime

# ─── Datos scrapeados de Wikipedia ──────────────────────────────────────────

# WCQ 2026 UEFA - Grupo A
WCQ_GROUP_A = [
    {"date":"2025-09-04","home":"Luxembourg","home_goals":1,"away_goals":3,"away":"Northern Ireland"},
    {"date":"2025-09-04","home":"Slovakia","home_goals":2,"away_goals":0,"away":"Germany"},
    {"date":"2025-09-07","home":"Luxembourg","home_goals":0,"away_goals":1,"away":"Slovakia"},
    {"date":"2025-09-07","home":"Germany","home_goals":3,"away_goals":1,"away":"Northern Ireland"},
    {"date":"2025-10-10","home":"Northern Ireland","home_goals":2,"away_goals":0,"away":"Slovakia"},
    {"date":"2025-10-10","home":"Germany","home_goals":4,"away_goals":0,"away":"Luxembourg"},
    {"date":"2025-10-13","home":"Northern Ireland","home_goals":0,"away_goals":1,"away":"Germany"},
    {"date":"2025-10-13","home":"Slovakia","home_goals":2,"away_goals":0,"away":"Luxembourg"},
    {"date":"2025-11-14","home":"Luxembourg","home_goals":0,"away_goals":2,"away":"Germany"},
    {"date":"2025-11-14","home":"Slovakia","home_goals":1,"away_goals":0,"away":"Northern Ireland"},
    {"date":"2025-11-17","home":"Northern Ireland","home_goals":1,"away_goals":0,"away":"Luxembourg"},
    {"date":"2025-11-17","home":"Germany","home_goals":6,"away_goals":0,"away":"Slovakia"},
]

# WCQ 2026 UEFA - Grupo B
WCQ_GROUP_B = [
    {"date":"2025-09-05","home":"Slovenia","home_goals":2,"away_goals":2,"away":"Sweden"},
    {"date":"2025-09-05","home":"Switzerland","home_goals":4,"away_goals":0,"away":"Kosovo"},
    {"date":"2025-09-08","home":"Kosovo","home_goals":2,"away_goals":0,"away":"Sweden"},
    {"date":"2025-09-08","home":"Switzerland","home_goals":3,"away_goals":0,"away":"Slovenia"},
    {"date":"2025-10-10","home":"Kosovo","home_goals":0,"away_goals":0,"away":"Slovenia"},
    {"date":"2025-10-10","home":"Sweden","home_goals":0,"away_goals":2,"away":"Switzerland"},
    {"date":"2025-10-13","home":"Slovenia","home_goals":0,"away_goals":0,"away":"Switzerland"},
    {"date":"2025-10-13","home":"Sweden","home_goals":0,"away_goals":1,"away":"Kosovo"},
    {"date":"2025-11-15","home":"Slovenia","home_goals":0,"away_goals":2,"away":"Kosovo"},
    {"date":"2025-11-15","home":"Switzerland","home_goals":4,"away_goals":1,"away":"Sweden"},
    {"date":"2025-11-18","home":"Kosovo","home_goals":1,"away_goals":1,"away":"Switzerland"},
    {"date":"2025-11-18","home":"Sweden","home_goals":1,"away_goals":1,"away":"Slovenia"},
]

# WCQ 2026 UEFA - Grupo C
WCQ_GROUP_C = [
    {"date":"2025-09-05","home":"Greece","home_goals":5,"away_goals":1,"away":"Belarus"},
    {"date":"2025-09-05","home":"Denmark","home_goals":0,"away_goals":0,"away":"Scotland"},
    {"date":"2025-09-08","home":"Belarus","home_goals":0,"away_goals":2,"away":"Scotland"},
    {"date":"2025-09-08","home":"Greece","home_goals":0,"away_goals":3,"away":"Denmark"},
    {"date":"2025-10-09","home":"Belarus","home_goals":0,"away_goals":6,"away":"Denmark"},
    {"date":"2025-10-09","home":"Scotland","home_goals":3,"away_goals":1,"away":"Greece"},
    {"date":"2025-10-12","home":"Scotland","home_goals":2,"away_goals":1,"away":"Belarus"},
    {"date":"2025-10-12","home":"Denmark","home_goals":3,"away_goals":1,"away":"Greece"},
    {"date":"2025-11-15","home":"Greece","home_goals":3,"away_goals":2,"away":"Scotland"},
    {"date":"2025-11-15","home":"Denmark","home_goals":2,"away_goals":2,"away":"Belarus"},
    {"date":"2025-11-18","home":"Belarus","home_goals":0,"away_goals":0,"away":"Greece"},
    {"date":"2025-11-18","home":"Scotland","home_goals":4,"away_goals":2,"away":"Denmark"},
]

# WCQ 2026 UEFA - Grupo D
WCQ_GROUP_D = [
    {"date":"2025-09-05","home":"Iceland","home_goals":5,"away_goals":0,"away":"Azerbaijan"},
    {"date":"2025-09-05","home":"Ukraine","home_goals":0,"away_goals":2,"away":"France"},
    {"date":"2025-09-09","home":"Azerbaijan","home_goals":1,"away_goals":1,"away":"Ukraine"},
    {"date":"2025-09-09","home":"France","home_goals":2,"away_goals":1,"away":"Iceland"},
    {"date":"2025-10-10","home":"Iceland","home_goals":3,"away_goals":5,"away":"Ukraine"},
    {"date":"2025-10-10","home":"France","home_goals":3,"away_goals":0,"away":"Azerbaijan"},
    {"date":"2025-10-13","home":"Iceland","home_goals":2,"away_goals":2,"away":"France"},
    {"date":"2025-10-13","home":"Ukraine","home_goals":2,"away_goals":1,"away":"Azerbaijan"},
    {"date":"2025-11-13","home":"Azerbaijan","home_goals":0,"away_goals":2,"away":"Iceland"},
    {"date":"2025-11-13","home":"France","home_goals":4,"away_goals":0,"away":"Ukraine"},
    {"date":"2025-11-16","home":"Azerbaijan","home_goals":1,"away_goals":3,"away":"France"},
    {"date":"2025-11-16","home":"Ukraine","home_goals":2,"away_goals":0,"away":"Iceland"},
]

# WCQ 2026 UEFA - Grupo E
WCQ_GROUP_E = [
    {"date":"2025-09-04","home":"Georgia","home_goals":2,"away_goals":3,"away":"Turkey"},
    {"date":"2025-09-04","home":"Bulgaria","home_goals":0,"away_goals":3,"away":"Spain"},
    {"date":"2025-09-07","home":"Georgia","home_goals":3,"away_goals":0,"away":"Bulgaria"},
    {"date":"2025-09-07","home":"Turkey","home_goals":0,"away_goals":6,"away":"Spain"},
    {"date":"2025-10-11","home":"Bulgaria","home_goals":1,"away_goals":6,"away":"Turkey"},
    {"date":"2025-10-11","home":"Spain","home_goals":2,"away_goals":0,"away":"Georgia"},
    {"date":"2025-10-14","home":"Turkey","home_goals":4,"away_goals":1,"away":"Georgia"},
    {"date":"2025-10-14","home":"Spain","home_goals":4,"away_goals":0,"away":"Bulgaria"},
    {"date":"2025-11-15","home":"Georgia","home_goals":0,"away_goals":4,"away":"Spain"},
    {"date":"2025-11-15","home":"Turkey","home_goals":2,"away_goals":0,"away":"Bulgaria"},
    {"date":"2025-11-18","home":"Bulgaria","home_goals":2,"away_goals":1,"away":"Georgia"},
    {"date":"2025-11-18","home":"Spain","home_goals":2,"away_goals":2,"away":"Turkey"},
]

# WCQ 2026 UEFA - Grupo F
WCQ_GROUP_F = [
    {"date":"2025-09-06","home":"Armenia","home_goals":0,"away_goals":5,"away":"Portugal"},
    {"date":"2025-09-06","home":"Republic of Ireland","home_goals":2,"away_goals":2,"away":"Hungary"},
    {"date":"2025-09-09","home":"Armenia","home_goals":2,"away_goals":1,"away":"Republic of Ireland"},
    {"date":"2025-09-09","home":"Hungary","home_goals":2,"away_goals":3,"away":"Portugal"},
    {"date":"2025-10-11","home":"Hungary","home_goals":2,"away_goals":0,"away":"Armenia"},
    {"date":"2025-10-11","home":"Portugal","home_goals":1,"away_goals":0,"away":"Republic of Ireland"},
    {"date":"2025-10-14","home":"Republic of Ireland","home_goals":1,"away_goals":0,"away":"Armenia"},
    {"date":"2025-10-14","home":"Portugal","home_goals":2,"away_goals":2,"away":"Hungary"},
    {"date":"2025-11-13","home":"Armenia","home_goals":0,"away_goals":1,"away":"Hungary"},
    {"date":"2025-11-13","home":"Republic of Ireland","home_goals":2,"away_goals":0,"away":"Portugal"},
    {"date":"2025-11-16","home":"Hungary","home_goals":2,"away_goals":3,"away":"Republic of Ireland"},
    {"date":"2025-11-16","home":"Portugal","home_goals":9,"away_goals":1,"away":"Armenia"},
]

# WCQ 2026 UEFA - Grupo G
WCQ_GROUP_G = [
    {"date":"2025-03-21","home":"Malta","home_goals":0,"away_goals":1,"away":"Finland"},
    {"date":"2025-03-21","home":"Poland","home_goals":1,"away_goals":0,"away":"Lithuania"},
    {"date":"2025-03-24","home":"Lithuania","home_goals":2,"away_goals":2,"away":"Finland"},
    {"date":"2025-03-24","home":"Poland","home_goals":2,"away_goals":0,"away":"Malta"},
    {"date":"2025-06-07","home":"Malta","home_goals":0,"away_goals":0,"away":"Lithuania"},
    {"date":"2025-06-07","home":"Finland","home_goals":0,"away_goals":2,"away":"Netherlands"},
    {"date":"2025-06-10","home":"Finland","home_goals":2,"away_goals":1,"away":"Poland"},
    {"date":"2025-06-10","home":"Netherlands","home_goals":8,"away_goals":0,"away":"Malta"},
    {"date":"2025-09-04","home":"Lithuania","home_goals":1,"away_goals":1,"away":"Malta"},
    {"date":"2025-09-04","home":"Netherlands","home_goals":1,"away_goals":1,"away":"Poland"},
    {"date":"2025-09-07","home":"Lithuania","home_goals":2,"away_goals":3,"away":"Netherlands"},
    {"date":"2025-09-07","home":"Poland","home_goals":3,"away_goals":1,"away":"Finland"},
    {"date":"2025-10-09","home":"Finland","home_goals":2,"away_goals":1,"away":"Lithuania"},
    {"date":"2025-10-09","home":"Malta","home_goals":0,"away_goals":4,"away":"Netherlands"},
    {"date":"2025-10-12","home":"Netherlands","home_goals":4,"away_goals":0,"away":"Finland"},
    {"date":"2025-10-12","home":"Lithuania","home_goals":0,"away_goals":2,"away":"Poland"},
    {"date":"2025-11-14","home":"Finland","home_goals":0,"away_goals":1,"away":"Malta"},
    {"date":"2025-11-14","home":"Poland","home_goals":1,"away_goals":1,"away":"Netherlands"},
    {"date":"2025-11-17","home":"Malta","home_goals":2,"away_goals":3,"away":"Poland"},
    {"date":"2025-11-17","home":"Netherlands","home_goals":4,"away_goals":0,"away":"Lithuania"},
]

# WCQ 2026 UEFA - Grupo H
WCQ_GROUP_H = [
    {"date":"2025-03-21","home":"Cyprus","home_goals":2,"away_goals":0,"away":"San Marino"},
    {"date":"2025-03-21","home":"Romania","home_goals":0,"away_goals":1,"away":"Bosnia and Herzegovina"},
    {"date":"2025-03-24","home":"Bosnia and Herzegovina","home_goals":2,"away_goals":1,"away":"Cyprus"},
    {"date":"2025-03-24","home":"San Marino","home_goals":1,"away_goals":5,"away":"Romania"},
    {"date":"2025-06-07","home":"Bosnia and Herzegovina","home_goals":1,"away_goals":0,"away":"San Marino"},
    {"date":"2025-06-07","home":"Austria","home_goals":2,"away_goals":1,"away":"Romania"},
    {"date":"2025-06-10","home":"Romania","home_goals":2,"away_goals":0,"away":"Cyprus"},
    {"date":"2025-06-10","home":"San Marino","home_goals":0,"away_goals":4,"away":"Austria"},
    {"date":"2025-09-06","home":"Austria","home_goals":1,"away_goals":0,"away":"Cyprus"},
    {"date":"2025-09-06","home":"San Marino","home_goals":0,"away_goals":6,"away":"Bosnia and Herzegovina"},
    {"date":"2025-09-09","home":"Bosnia and Herzegovina","home_goals":1,"away_goals":2,"away":"Austria"},
    {"date":"2025-09-09","home":"Cyprus","home_goals":2,"away_goals":2,"away":"Romania"},
    {"date":"2025-10-09","home":"Austria","home_goals":10,"away_goals":0,"away":"San Marino"},
    {"date":"2025-10-09","home":"Cyprus","home_goals":2,"away_goals":2,"away":"Bosnia and Herzegovina"},
    {"date":"2025-10-12","home":"San Marino","home_goals":0,"away_goals":4,"away":"Cyprus"},
    {"date":"2025-10-12","home":"Romania","home_goals":1,"away_goals":0,"away":"Austria"},
    {"date":"2025-11-15","home":"Cyprus","home_goals":0,"away_goals":2,"away":"Austria"},
    {"date":"2025-11-15","home":"Bosnia and Herzegovina","home_goals":3,"away_goals":1,"away":"Romania"},
    {"date":"2025-11-18","home":"Austria","home_goals":1,"away_goals":1,"away":"Bosnia and Herzegovina"},
    {"date":"2025-11-18","home":"Romania","home_goals":7,"away_goals":1,"away":"San Marino"},
]

# WCQ 2026 UEFA - Grupo I
WCQ_GROUP_I = [
    {"date":"2025-03-22","home":"Moldova","home_goals":0,"away_goals":5,"away":"Norway"},
    {"date":"2025-03-22","home":"Israel","home_goals":2,"away_goals":1,"away":"Estonia"},
    {"date":"2025-03-25","home":"Moldova","home_goals":2,"away_goals":3,"away":"Estonia"},
    {"date":"2025-03-25","home":"Israel","home_goals":2,"away_goals":4,"away":"Norway"},
    {"date":"2025-06-06","home":"Estonia","home_goals":1,"away_goals":3,"away":"Israel"},
    {"date":"2025-06-06","home":"Norway","home_goals":3,"away_goals":0,"away":"Italy"},
    {"date":"2025-06-09","home":"Estonia","home_goals":0,"away_goals":1,"away":"Norway"},
    {"date":"2025-06-09","home":"Italy","home_goals":2,"away_goals":0,"away":"Moldova"},
    {"date":"2025-09-05","home":"Moldova","home_goals":0,"away_goals":4,"away":"Israel"},
    {"date":"2025-09-05","home":"Italy","home_goals":5,"away_goals":0,"away":"Estonia"},
    {"date":"2025-09-08","home":"Israel","home_goals":4,"away_goals":5,"away":"Italy"},
    {"date":"2025-09-09","home":"Norway","home_goals":11,"away_goals":1,"away":"Moldova"},
    {"date":"2025-10-11","home":"Norway","home_goals":5,"away_goals":0,"away":"Israel"},
    {"date":"2025-10-11","home":"Estonia","home_goals":1,"away_goals":3,"away":"Italy"},
    {"date":"2025-10-14","home":"Estonia","home_goals":1,"away_goals":1,"away":"Moldova"},
    {"date":"2025-10-14","home":"Italy","home_goals":3,"away_goals":0,"away":"Israel"},
    {"date":"2025-11-13","home":"Norway","home_goals":4,"away_goals":1,"away":"Estonia"},
    {"date":"2025-11-13","home":"Moldova","home_goals":0,"away_goals":2,"away":"Italy"},
    {"date":"2025-11-16","home":"Israel","home_goals":4,"away_goals":1,"away":"Moldova"},
    {"date":"2025-11-16","home":"Italy","home_goals":1,"away_goals":4,"away":"Norway"},
]

# WCQ 2026 UEFA - Grupo J
WCQ_GROUP_J = [
    {"date":"2025-03-22","home":"Liechtenstein","home_goals":0,"away_goals":3,"away":"North Macedonia"},
    {"date":"2025-03-22","home":"Wales","home_goals":3,"away_goals":1,"away":"Kazakhstan"},
    {"date":"2025-03-25","home":"Liechtenstein","home_goals":0,"away_goals":2,"away":"Kazakhstan"},
    {"date":"2025-03-25","home":"North Macedonia","home_goals":1,"away_goals":1,"away":"Wales"},
    {"date":"2025-06-06","home":"North Macedonia","home_goals":1,"away_goals":1,"away":"Belgium"},
    {"date":"2025-06-06","home":"Wales","home_goals":3,"away_goals":0,"away":"Liechtenstein"},
    {"date":"2025-06-09","home":"Kazakhstan","home_goals":0,"away_goals":1,"away":"North Macedonia"},
    {"date":"2025-06-09","home":"Belgium","home_goals":4,"away_goals":3,"away":"Wales"},
    {"date":"2025-09-04","home":"Kazakhstan","home_goals":0,"away_goals":1,"away":"Wales"},
    {"date":"2025-09-04","home":"Liechtenstein","home_goals":0,"away_goals":6,"away":"Belgium"},
    {"date":"2025-09-07","home":"North Macedonia","home_goals":5,"away_goals":0,"away":"Liechtenstein"},
    {"date":"2025-09-07","home":"Belgium","home_goals":6,"away_goals":0,"away":"Kazakhstan"},
    {"date":"2025-10-10","home":"Kazakhstan","home_goals":4,"away_goals":0,"away":"Liechtenstein"},
    {"date":"2025-10-10","home":"Belgium","home_goals":0,"away_goals":0,"away":"North Macedonia"},
    {"date":"2025-10-13","home":"North Macedonia","home_goals":1,"away_goals":1,"away":"Kazakhstan"},
    {"date":"2025-10-13","home":"Wales","home_goals":2,"away_goals":4,"away":"Belgium"},
    {"date":"2025-11-15","home":"Kazakhstan","home_goals":1,"away_goals":1,"away":"Belgium"},
    {"date":"2025-11-15","home":"Liechtenstein","home_goals":0,"away_goals":1,"away":"Wales"},
    {"date":"2025-11-18","home":"Belgium","home_goals":7,"away_goals":0,"away":"Liechtenstein"},
    {"date":"2025-11-18","home":"Wales","home_goals":7,"away_goals":1,"away":"North Macedonia"},
]

# WCQ 2026 UEFA - Grupo K
WCQ_GROUP_K = [
    {"date":"2025-03-21","home":"Andorra","home_goals":0,"away_goals":1,"away":"Latvia"},
    {"date":"2025-03-21","home":"England","home_goals":2,"away_goals":0,"away":"Albania"},
    {"date":"2025-03-24","home":"Albania","home_goals":3,"away_goals":0,"away":"Andorra"},
    {"date":"2025-03-24","home":"England","home_goals":3,"away_goals":0,"away":"Latvia"},
    {"date":"2025-06-07","home":"Andorra","home_goals":0,"away_goals":1,"away":"England"},
    {"date":"2025-06-07","home":"Albania","home_goals":0,"away_goals":0,"away":"Serbia"},
    {"date":"2025-06-10","home":"Latvia","home_goals":1,"away_goals":1,"away":"Albania"},
    {"date":"2025-06-10","home":"Serbia","home_goals":3,"away_goals":0,"away":"Andorra"},
    {"date":"2025-09-06","home":"Latvia","home_goals":0,"away_goals":1,"away":"Serbia"},
    {"date":"2025-09-06","home":"England","home_goals":2,"away_goals":0,"away":"Andorra"},
    {"date":"2025-09-09","home":"Albania","home_goals":1,"away_goals":0,"away":"Latvia"},
    {"date":"2025-09-09","home":"Serbia","home_goals":0,"away_goals":5,"away":"England"},
    {"date":"2025-10-11","home":"Latvia","home_goals":2,"away_goals":2,"away":"Andorra"},
    {"date":"2025-10-11","home":"Serbia","home_goals":0,"away_goals":1,"away":"Albania"},
    {"date":"2025-10-14","home":"Andorra","home_goals":1,"away_goals":3,"away":"Serbia"},
    {"date":"2025-10-14","home":"Latvia","home_goals":0,"away_goals":5,"away":"England"},
    {"date":"2025-11-13","home":"Andorra","home_goals":0,"away_goals":1,"away":"Albania"},
    {"date":"2025-11-13","home":"England","home_goals":2,"away_goals":0,"away":"Serbia"},
    {"date":"2025-11-16","home":"Albania","home_goals":0,"away_goals":2,"away":"England"},
    {"date":"2025-11-16","home":"Serbia","home_goals":2,"away_goals":1,"away":"Latvia"},
]

# WCQ 2026 UEFA - Grupo L
WCQ_GROUP_L = [
    {"date":"2025-03-22","home":"Montenegro","home_goals":3,"away_goals":1,"away":"Gibraltar"},
    {"date":"2025-03-22","home":"Czech Republic","home_goals":2,"away_goals":1,"away":"Faroe Islands"},
    {"date":"2025-03-25","home":"Gibraltar","home_goals":0,"away_goals":4,"away":"Czech Republic"},
    {"date":"2025-03-25","home":"Montenegro","home_goals":1,"away_goals":0,"away":"Faroe Islands"},
    {"date":"2025-06-06","home":"Czech Republic","home_goals":2,"away_goals":0,"away":"Montenegro"},
    {"date":"2025-06-06","home":"Gibraltar","home_goals":0,"away_goals":7,"away":"Croatia"},
    {"date":"2025-06-09","home":"Faroe Islands","home_goals":2,"away_goals":1,"away":"Gibraltar"},
    {"date":"2025-06-09","home":"Croatia","home_goals":5,"away_goals":1,"away":"Czech Republic"},
    {"date":"2025-09-05","home":"Faroe Islands","home_goals":0,"away_goals":1,"away":"Croatia"},
    {"date":"2025-09-05","home":"Montenegro","home_goals":0,"away_goals":2,"away":"Czech Republic"},
    {"date":"2025-09-08","home":"Gibraltar","home_goals":0,"away_goals":1,"away":"Faroe Islands"},
    {"date":"2025-09-08","home":"Croatia","home_goals":4,"away_goals":0,"away":"Montenegro"},
    {"date":"2025-10-09","home":"Czech Republic","home_goals":0,"away_goals":0,"away":"Croatia"},
    {"date":"2025-10-09","home":"Faroe Islands","home_goals":4,"away_goals":0,"away":"Montenegro"},
    {"date":"2025-10-12","home":"Faroe Islands","home_goals":2,"away_goals":1,"away":"Czech Republic"},
    {"date":"2025-10-12","home":"Croatia","home_goals":3,"away_goals":0,"away":"Gibraltar"},
    {"date":"2025-11-14","home":"Gibraltar","home_goals":1,"away_goals":2,"away":"Montenegro"},
    {"date":"2025-11-14","home":"Croatia","home_goals":3,"away_goals":1,"away":"Faroe Islands"},
    {"date":"2025-11-17","home":"Czech Republic","home_goals":6,"away_goals":0,"away":"Gibraltar"},
    {"date":"2025-11-17","home":"Montenegro","home_goals":2,"away_goals":3,"away":"Croatia"},
]

# Nations League 2024-25 Liga A
NL_A = [
    {"date":"2024-09-05","home":"Portugal","home_goals":2,"away_goals":1,"away":"Croatia"},
    {"date":"2024-09-05","home":"Scotland","home_goals":2,"away_goals":3,"away":"Poland"},
    {"date":"2024-09-08","home":"Croatia","home_goals":1,"away_goals":0,"away":"Poland"},
    {"date":"2024-09-08","home":"Portugal","home_goals":2,"away_goals":1,"away":"Scotland"},
    {"date":"2024-09-06","home":"Belgium","home_goals":3,"away_goals":1,"away":"Israel"},
    {"date":"2024-09-06","home":"France","home_goals":1,"away_goals":3,"away":"Italy"},
    {"date":"2024-09-09","home":"France","home_goals":2,"away_goals":0,"away":"Belgium"},
    {"date":"2024-09-09","home":"Israel","home_goals":1,"away_goals":2,"away":"Italy"},
    {"date":"2024-09-07","home":"Germany","home_goals":5,"away_goals":0,"away":"Hungary"},
    {"date":"2024-09-07","home":"Netherlands","home_goals":5,"away_goals":2,"away":"Bosnia and Herzegovina"},
    {"date":"2024-09-10","home":"Hungary","home_goals":0,"away_goals":0,"away":"Bosnia and Herzegovina"},
    {"date":"2024-09-10","home":"Netherlands","home_goals":2,"away_goals":2,"away":"Germany"},
    {"date":"2024-10-12","home":"Croatia","home_goals":2,"away_goals":1,"away":"Scotland"},
    {"date":"2024-10-12","home":"Poland","home_goals":1,"away_goals":3,"away":"Portugal"},
    {"date":"2024-10-15","home":"Poland","home_goals":3,"away_goals":3,"away":"Croatia"},
    {"date":"2024-10-15","home":"Scotland","home_goals":0,"away_goals":0,"away":"Portugal"},
    {"date":"2024-10-10","home":"Israel","home_goals":1,"away_goals":4,"away":"France"},
    {"date":"2024-10-10","home":"Italy","home_goals":2,"away_goals":2,"away":"Belgium"},
    {"date":"2024-10-14","home":"Belgium","home_goals":1,"away_goals":2,"away":"France"},
    {"date":"2024-10-14","home":"Italy","home_goals":4,"away_goals":1,"away":"Israel"},
    {"date":"2024-10-11","home":"Bosnia and Herzegovina","home_goals":1,"away_goals":2,"away":"Germany"},
    {"date":"2024-10-11","home":"Hungary","home_goals":1,"away_goals":1,"away":"Netherlands"},
    {"date":"2024-10-14","home":"Germany","home_goals":1,"away_goals":0,"away":"Netherlands"},
    {"date":"2024-11-15","home":"Portugal","home_goals":5,"away_goals":1,"away":"Poland"},
    {"date":"2024-11-15","home":"Scotland","home_goals":1,"away_goals":0,"away":"Croatia"},
    {"date":"2024-11-18","home":"Croatia","home_goals":1,"away_goals":1,"away":"Portugal"},
    {"date":"2024-11-18","home":"Poland","home_goals":1,"away_goals":2,"away":"Scotland"},
    {"date":"2024-11-14","home":"Belgium","home_goals":0,"away_goals":1,"away":"Italy"},
    {"date":"2024-11-14","home":"France","home_goals":0,"away_goals":0,"away":"Israel"},
    {"date":"2024-11-17","home":"Israel","home_goals":1,"away_goals":0,"away":"Belgium"},
    {"date":"2024-11-17","home":"Italy","home_goals":1,"away_goals":3,"away":"France"},
    {"date":"2024-11-16","home":"Germany","home_goals":7,"away_goals":0,"away":"Bosnia and Herzegovina"},
    {"date":"2024-11-16","home":"Netherlands","home_goals":4,"away_goals":0,"away":"Hungary"},
    {"date":"2024-11-19","home":"Bosnia and Herzegovina","home_goals":1,"away_goals":1,"away":"Netherlands"},
    {"date":"2024-11-19","home":"Hungary","home_goals":1,"away_goals":1,"away":"Germany"},
]

# Nations League 2024-25 Liga B
NL_B = [
    {"date":"2024-09-07","home":"Georgia","home_goals":4,"away_goals":1,"away":"Czech Republic"},
    {"date":"2024-09-07","home":"Ukraine","home_goals":1,"away_goals":2,"away":"Albania"},
    {"date":"2024-09-10","home":"Albania","home_goals":0,"away_goals":1,"away":"Georgia"},
    {"date":"2024-09-10","home":"Czech Republic","home_goals":3,"away_goals":2,"away":"Ukraine"},
    {"date":"2024-10-11","home":"Czech Republic","home_goals":2,"away_goals":0,"away":"Albania"},
    {"date":"2024-10-11","home":"Ukraine","home_goals":1,"away_goals":0,"away":"Georgia"},
    {"date":"2024-10-14","home":"Georgia","home_goals":0,"away_goals":1,"away":"Albania"},
    {"date":"2024-10-14","home":"Ukraine","home_goals":1,"away_goals":1,"away":"Czech Republic"},
    {"date":"2024-11-16","home":"Georgia","home_goals":1,"away_goals":1,"away":"Ukraine"},
    {"date":"2024-11-16","home":"Albania","home_goals":0,"away_goals":0,"away":"Czech Republic"},
    {"date":"2024-11-19","home":"Albania","home_goals":1,"away_goals":2,"away":"Ukraine"},
    {"date":"2024-11-19","home":"Czech Republic","home_goals":2,"away_goals":1,"away":"Georgia"},
    {"date":"2024-09-07","home":"Republic of Ireland","home_goals":0,"away_goals":2,"away":"England"},
    {"date":"2024-09-07","home":"Greece","home_goals":3,"away_goals":0,"away":"Finland"},
    {"date":"2024-09-10","home":"England","home_goals":2,"away_goals":0,"away":"Finland"},
    {"date":"2024-09-10","home":"Republic of Ireland","home_goals":0,"away_goals":2,"away":"Greece"},
    {"date":"2024-10-10","home":"England","home_goals":1,"away_goals":2,"away":"Greece"},
    {"date":"2024-10-10","home":"Finland","home_goals":1,"away_goals":2,"away":"Republic of Ireland"},
    {"date":"2024-10-13","home":"Finland","home_goals":1,"away_goals":3,"away":"England"},
    {"date":"2024-10-13","home":"Greece","home_goals":2,"away_goals":0,"away":"Republic of Ireland"},
    {"date":"2024-11-14","home":"Greece","home_goals":0,"away_goals":3,"away":"England"},
    {"date":"2024-11-14","home":"Republic of Ireland","home_goals":1,"away_goals":0,"away":"Finland"},
    {"date":"2024-11-17","home":"England","home_goals":5,"away_goals":0,"away":"Republic of Ireland"},
    {"date":"2024-11-17","home":"Finland","home_goals":0,"away_goals":2,"away":"Greece"},
    {"date":"2024-09-06","home":"Kazakhstan","home_goals":0,"away_goals":0,"away":"Norway"},
    {"date":"2024-09-06","home":"Slovenia","home_goals":1,"away_goals":1,"away":"Austria"},
    {"date":"2024-09-09","home":"Norway","home_goals":2,"away_goals":1,"away":"Austria"},
    {"date":"2024-09-09","home":"Slovenia","home_goals":3,"away_goals":0,"away":"Kazakhstan"},
    {"date":"2024-10-10","home":"Austria","home_goals":4,"away_goals":0,"away":"Kazakhstan"},
    {"date":"2024-10-10","home":"Norway","home_goals":3,"away_goals":0,"away":"Slovenia"},
    {"date":"2024-10-13","home":"Kazakhstan","home_goals":0,"away_goals":1,"away":"Slovenia"},
    {"date":"2024-10-13","home":"Austria","home_goals":5,"away_goals":1,"away":"Norway"},
    {"date":"2024-11-14","home":"Kazakhstan","home_goals":0,"away_goals":2,"away":"Austria"},
    {"date":"2024-11-14","home":"Slovenia","home_goals":1,"away_goals":4,"away":"Norway"},
    {"date":"2024-11-17","home":"Austria","home_goals":1,"away_goals":1,"away":"Slovenia"},
    {"date":"2024-11-17","home":"Norway","home_goals":5,"away_goals":0,"away":"Kazakhstan"},
    {"date":"2024-09-06","home":"Iceland","home_goals":2,"away_goals":0,"away":"Montenegro"},
    {"date":"2024-09-06","home":"Wales","home_goals":0,"away_goals":0,"away":"Turkey"},
    {"date":"2024-09-09","home":"Montenegro","home_goals":1,"away_goals":2,"away":"Wales"},
    {"date":"2024-09-10","home":"Turkey","home_goals":3,"away_goals":1,"away":"Iceland"},
    {"date":"2024-10-10","home":"Iceland","home_goals":2,"away_goals":4,"away":"Turkey"},
    {"date":"2024-10-10","home":"Wales","home_goals":4,"away_goals":1,"away":"Iceland"},
    {"date":"2024-10-13","home":"Turkey","home_goals":1,"away_goals":0,"away":"Montenegro"},
    {"date":"2024-10-13","home":"Iceland","home_goals":2,"away_goals":2,"away":"Wales"},
    {"date":"2024-11-16","home":"Turkey","home_goals":3,"away_goals":1,"away":"Montenegro"},
    {"date":"2024-11-16","home":"Wales","home_goals":1,"away_goals":0,"away":"Montenegro"},
    {"date":"2024-11-17","home":"Iceland","home_goals":1,"away_goals":0,"away":"Montenegro"},
    {"date":"2024-11-17","home":"Wales","home_goals":2,"away_goals":0,"away":"Turkey"},
]

# Nations League 2024-25 Liga C
NL_C = [
    {"date":"2024-09-05","home":"Azerbaijan","home_goals":1,"away_goals":3,"away":"Sweden"},
    {"date":"2024-09-05","home":"Estonia","home_goals":0,"away_goals":1,"away":"Slovakia"},
    {"date":"2024-09-08","home":"Slovakia","home_goals":2,"away_goals":0,"away":"Azerbaijan"},
    {"date":"2024-09-08","home":"Sweden","home_goals":3,"away_goals":0,"away":"Estonia"},
    {"date":"2024-10-11","home":"Estonia","home_goals":3,"away_goals":1,"away":"Azerbaijan"},
    {"date":"2024-10-11","home":"Slovakia","home_goals":2,"away_goals":2,"away":"Sweden"},
    {"date":"2024-10-14","home":"Azerbaijan","home_goals":1,"away_goals":3,"away":"Slovakia"},
    {"date":"2024-10-14","home":"Estonia","home_goals":0,"away_goals":3,"away":"Sweden"},
    {"date":"2024-11-16","home":"Azerbaijan","home_goals":0,"away_goals":0,"away":"Estonia"},
    {"date":"2024-11-16","home":"Sweden","home_goals":2,"away_goals":1,"away":"Slovakia"},
    {"date":"2024-11-19","home":"Slovakia","home_goals":1,"away_goals":0,"away":"Estonia"},
    {"date":"2024-11-19","home":"Sweden","home_goals":6,"away_goals":0,"away":"Azerbaijan"},
    {"date":"2024-09-06","home":"Lithuania","home_goals":0,"away_goals":1,"away":"Cyprus"},
    {"date":"2024-09-06","home":"Kosovo","home_goals":0,"away_goals":3,"away":"Romania"},
    {"date":"2024-09-09","home":"Cyprus","home_goals":0,"away_goals":4,"away":"Kosovo"},
    {"date":"2024-09-09","home":"Romania","home_goals":3,"away_goals":1,"away":"Lithuania"},
    {"date":"2024-10-12","home":"Lithuania","home_goals":1,"away_goals":2,"away":"Kosovo"},
    {"date":"2024-10-12","home":"Cyprus","home_goals":0,"away_goals":3,"away":"Romania"},
    {"date":"2024-10-15","home":"Kosovo","home_goals":3,"away_goals":0,"away":"Cyprus"},
    {"date":"2024-10-15","home":"Lithuania","home_goals":1,"away_goals":2,"away":"Romania"},
    {"date":"2024-11-15","home":"Cyprus","home_goals":2,"away_goals":1,"away":"Lithuania"},
    {"date":"2024-11-15","home":"Romania","home_goals":3,"away_goals":0,"away":"Kosovo"},
    {"date":"2024-11-18","home":"Kosovo","home_goals":1,"away_goals":0,"away":"Lithuania"},
    {"date":"2024-11-18","home":"Romania","home_goals":4,"away_goals":1,"away":"Cyprus"},
    {"date":"2024-09-05","home":"Belarus","home_goals":0,"away_goals":0,"away":"Bulgaria"},
    {"date":"2024-09-05","home":"Northern Ireland","home_goals":2,"away_goals":0,"away":"Luxembourg"},
    {"date":"2024-09-08","home":"Luxembourg","home_goals":0,"away_goals":1,"away":"Belarus"},
    {"date":"2024-09-08","home":"Bulgaria","home_goals":1,"away_goals":0,"away":"Northern Ireland"},
    {"date":"2024-10-12","home":"Bulgaria","home_goals":0,"away_goals":0,"away":"Luxembourg"},
    {"date":"2024-10-12","home":"Belarus","home_goals":0,"away_goals":0,"away":"Northern Ireland"},
    {"date":"2024-10-15","home":"Belarus","home_goals":1,"away_goals":1,"away":"Luxembourg"},
    {"date":"2024-10-15","home":"Northern Ireland","home_goals":5,"away_goals":0,"away":"Bulgaria"},
    {"date":"2024-11-15","home":"Luxembourg","home_goals":0,"away_goals":1,"away":"Bulgaria"},
    {"date":"2024-11-15","home":"Northern Ireland","home_goals":2,"away_goals":0,"away":"Belarus"},
    {"date":"2024-11-18","home":"Bulgaria","home_goals":1,"away_goals":1,"away":"Belarus"},
    {"date":"2024-11-18","home":"Luxembourg","home_goals":2,"away_goals":2,"away":"Northern Ireland"},
    {"date":"2024-09-07","home":"Faroe Islands","home_goals":1,"away_goals":1,"away":"North Macedonia"},
    {"date":"2024-09-07","home":"Armenia","home_goals":4,"away_goals":1,"away":"Latvia"},
    {"date":"2024-09-10","home":"Latvia","home_goals":1,"away_goals":0,"away":"Faroe Islands"},
    {"date":"2024-09-10","home":"North Macedonia","home_goals":2,"away_goals":0,"away":"Armenia"},
    {"date":"2024-10-11","home":"Armenia","home_goals":0,"away_goals":1,"away":"Faroe Islands"},
    {"date":"2024-10-11","home":"North Macedonia","home_goals":1,"away_goals":0,"away":"Latvia"},
    {"date":"2024-10-15","home":"Faroe Islands","home_goals":2,"away_goals":2,"away":"Armenia"},
    {"date":"2024-10-15","home":"Latvia","home_goals":1,"away_goals":2,"away":"North Macedonia"},
    {"date":"2024-11-15","home":"Faroe Islands","home_goals":1,"away_goals":1,"away":"Latvia"},
    {"date":"2024-11-15","home":"North Macedonia","home_goals":1,"away_goals":0,"away":"Armenia"},
    {"date":"2024-11-18","home":"Armenia","home_goals":2,"away_goals":0,"away":"Faroe Islands"},
    {"date":"2024-11-18","home":"Latvia","home_goals":0,"away_goals":3,"away":"North Macedonia"},
]

# Nations League 2024-25 Liga D
NL_D = [
    {"date":"2024-09-05","home":"San Marino","home_goals":1,"away_goals":0,"away":"Liechtenstein"},
    {"date":"2024-09-08","home":"Gibraltar","home_goals":2,"away_goals":2,"away":"Liechtenstein"},
    {"date":"2024-09-07","home":"Moldova","home_goals":2,"away_goals":0,"away":"Malta"},
    {"date":"2024-09-10","home":"Andorra","home_goals":0,"away_goals":1,"away":"Malta"},
    {"date":"2024-10-10","home":"Gibraltar","home_goals":1,"away_goals":0,"away":"San Marino"},
    {"date":"2024-10-10","home":"Moldova","home_goals":2,"away_goals":0,"away":"Andorra"},
    {"date":"2024-10-13","home":"Liechtenstein","home_goals":0,"away_goals":0,"away":"Gibraltar"},
    {"date":"2024-10-13","home":"Malta","home_goals":1,"away_goals":0,"away":"Moldova"},
    {"date":"2024-11-15","home":"San Marino","home_goals":1,"away_goals":1,"away":"Gibraltar"},
    {"date":"2024-11-16","home":"Andorra","home_goals":0,"away_goals":1,"away":"Moldova"},
    {"date":"2024-11-18","home":"Liechtenstein","home_goals":1,"away_goals":3,"away":"San Marino"},
    {"date":"2024-11-19","home":"Malta","home_goals":0,"away_goals":0,"away":"Andorra"},
]

# WCQ Playoffs (semi-finals, played 2026-03-26)
WCQ_PLAYOFFS = [
    {"date":"2026-03-26","home":"Italy","home_goals":2,"away_goals":0,"away":"Northern Ireland"},
    {"date":"2026-03-26","home":"Wales","home_goals":1,"away_goals":1,"away":"Bosnia and Herzegovina"},
    {"date":"2026-03-26","home":"Ukraine","home_goals":1,"away_goals":3,"away":"Sweden"},
    {"date":"2026-03-26","home":"Poland","home_goals":2,"away_goals":1,"away":"Albania"},
    {"date":"2026-03-26","home":"Turkey","home_goals":1,"away_goals":0,"away":"Romania"},
    {"date":"2026-03-26","home":"Slovakia","home_goals":3,"away_goals":4,"away":"Kosovo"},
    {"date":"2026-03-26","home":"Denmark","home_goals":4,"away_goals":0,"away":"North Macedonia"},
    {"date":"2026-03-26","home":"Czech Republic","home_goals":2,"away_goals":2,"away":"Republic of Ireland"},
]


# ─── Normalización de nombres ──────────────────────────────────────────────

NAME_MAP = {
    "Czech Republic": "Czechia",
    "Republic of Ireland": "Rep. Ireland",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
}


def normalize_name(name):
    return NAME_MAP.get(name, name)


def build_all_matches():
    """Consolida todos los partidos scrapeados en una lista unificada."""
    all_sources = [
        ("WCQ Group A", WCQ_GROUP_A),
        ("WCQ Group B", WCQ_GROUP_B),
        ("WCQ Group C", WCQ_GROUP_C),
        ("WCQ Group D", WCQ_GROUP_D),
        ("WCQ Group E", WCQ_GROUP_E),
        ("WCQ Group F", WCQ_GROUP_F),
        ("WCQ Group G", WCQ_GROUP_G),
        ("WCQ Group H", WCQ_GROUP_H),
        ("WCQ Group I", WCQ_GROUP_I),
        ("WCQ Group J", WCQ_GROUP_J),
        ("WCQ Group K", WCQ_GROUP_K),
        ("WCQ Group L", WCQ_GROUP_L),
        ("WCQ Playoffs", WCQ_PLAYOFFS),
        ("Nations League A", NL_A),
        ("Nations League B", NL_B),
        ("Nations League C", NL_C),
        ("Nations League D", NL_D),
    ]

    all_matches = []
    for source_name, matches in all_sources:
        for m in matches:
            all_matches.append({
                "date": m["date"],
                "competition": source_name,
                "home_team": normalize_name(m["home"]),
                "away_team": normalize_name(m["away"]),
                "home_goals": m["home_goals"],
                "away_goals": m["away_goals"],
            })

    # Deduplicar por (date, home, away)
    seen = set()
    unique = []
    for m in all_matches:
        key = (m["date"], m["home_team"], m["away_team"])
        if key not in seen:
            seen.add(key)
            unique.append(m)

    return sorted(unique, key=lambda x: x["date"])


def main():
    matches = build_all_matches()

    # Contar equipos únicos
    teams = set()
    for m in matches:
        teams.add(m["home_team"])
        teams.add(m["away_team"])

    print(f"Total partidos de selecciones nacionales: {len(matches)}")
    print(f"Selecciones únicas: {len(teams)}")
    print(f"Período: {matches[0]['date']} a {matches[-1]['date']}")

    # Guardar
    out_path = os.path.join(os.path.dirname(__file__), "national_matches.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)
    print(f"\nGuardado en: {out_path}")

    # Resumen por competición
    from collections import Counter
    comp_count = Counter(m["competition"] for m in matches)
    print(f"\nPartidos por competición:")
    for comp, count in sorted(comp_count.items()):
        print(f"  {comp}: {count}")


if __name__ == "__main__":
    main()
