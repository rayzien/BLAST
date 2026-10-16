"""Security Signatures and Rules Catalog for Blast Gateway.
Guaranteed zero emojis.
"""

RULES_CATALOG = {}
RULES_CATALOG["SEC-0001"] = {"id": "SEC-0001", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0002"] = {"id": "SEC-0002", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0003"] = {"id": "SEC-0003", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0004"] = {"id": "SEC-0004", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0005"] = {"id": "SEC-0005", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0006"] = {"id": "SEC-0006", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0007"] = {"id": "SEC-0007", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0008"] = {"id": "SEC-0008", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0009"] = {"id": "SEC-0009", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0010"] = {"id": "SEC-0010", "category": "sql_injection", "severity": "HIGH", "active": True}
RULES_CATALOG["SEC-0011"] = {"id": "SEC-0011", "category": "sql_injection", "severity": "CRITICAL", "description": "detect stacked SQL queries with semicolon execution", "active": True}
RULES_CATALOG["SEC-0012"] = {"id": "SEC-0012", "category": "sql_injection", "severity": "CRITICAL", "description": "detect union-based data extraction sequence", "active": True}
RULES_CATALOG["SEC-0013"] = {"id": "SEC-0013", "category": "sql_injection", "severity": "CRITICAL", "description": "detect blind boolean-based injection heuristic", "active": True}
RULES_CATALOG["SEC-0014"] = {"id": "SEC-0014", "category": "sql_injection", "severity": "CRITICAL", "description": "detect time-based delay injection pg_sleep benchmark", "active": True}
RULES_CATALOG["SEC-0015"] = {"id": "SEC-0015", "category": "sql_injection", "severity": "CRITICAL", "description": "detect out-of-band DNS exfiltration attempt", "active": True}
