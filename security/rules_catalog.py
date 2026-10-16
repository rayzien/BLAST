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
RULES_CATALOG["SEC-0016"] = {"id": "SEC-0016", "category": "sql_injection", "severity": "CRITICAL", "description": "detect comment delimiter sequence in query parameter", "active": True}
RULES_CATALOG["SEC-0017"] = {"id": "SEC-0017", "category": "sql_injection", "severity": "CRITICAL", "description": "detect OR 1=1 tautology pattern in filter string", "active": True}
RULES_CATALOG["SEC-0018"] = {"id": "SEC-0018", "category": "sql_injection", "severity": "CRITICAL", "description": "detect AND 1=1 tautology pattern in filter string", "active": True}
RULES_CATALOG["SEC-0019"] = {"id": "SEC-0019", "category": "sql_injection", "severity": "CRITICAL", "description": "detect information_schema table enumeration query", "active": True}
RULES_CATALOG["SEC-0020"] = {"id": "SEC-0020", "category": "sql_injection", "severity": "CRITICAL", "description": "detect pg_catalog metadata extraction pattern", "active": True}
RULES_CATALOG["SEC-0021"] = {"id": "SEC-0021", "category": "sql_injection", "severity": "CRITICAL", "description": "detect version fingerprinting database query", "active": True}
RULES_CATALOG["SEC-0022"] = {"id": "SEC-0022", "category": "sql_injection", "severity": "CRITICAL", "description": "detect cast operator injection to arbitrary types", "active": True}
RULES_CATALOG["SEC-0023"] = {"id": "SEC-0023", "category": "sql_injection", "severity": "CRITICAL", "description": "detect hex-encoded string literal SQL construct", "active": True}
RULES_CATALOG["SEC-0024"] = {"id": "SEC-0024", "category": "sql_injection", "severity": "CRITICAL", "description": "detect null byte injection inside string literal", "active": True}
RULES_CATALOG["SEC-0025"] = {"id": "SEC-0025", "category": "sql_injection", "severity": "CRITICAL", "description": "detect xp_cmdshell procedure invocation pattern", "active": True}
RULES_CATALOG["SEC-0026"] = {"id": "SEC-0026", "category": "sql_injection", "severity": "CRITICAL", "description": "detect sp_executesql dynamic execution pattern", "active": True}
RULES_CATALOG["SEC-0027"] = {"id": "SEC-0027", "category": "sql_injection", "severity": "CRITICAL", "description": "detect utl_http external transmission payload", "active": True}
RULES_CATALOG["SEC-0028"] = {"id": "SEC-0028", "category": "sql_injection", "severity": "CRITICAL", "description": "detect load_file filesystem access heuristic", "active": True}
RULES_CATALOG["SEC-0029"] = {"id": "SEC-0029", "category": "sql_injection", "severity": "CRITICAL", "description": "detect into outfile web shell creation attempt", "active": True}
RULES_CATALOG["SEC-0030"] = {"id": "SEC-0030", "category": "sql_injection", "severity": "CRITICAL", "description": "detect into dumpfile binary dumping payload", "active": True}
RULES_CATALOG["SEC-0031"] = {"id": "SEC-0031", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block __proto__ root object manipulation key", "active": True}
RULES_CATALOG["SEC-0032"] = {"id": "SEC-0032", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block constructor property prototype chain pollution", "active": True}
RULES_CATALOG["SEC-0033"] = {"id": "SEC-0033", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block prototype descriptor override attempt", "active": True}
RULES_CATALOG["SEC-0034"] = {"id": "SEC-0034", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block Object.prototype pollution in JSON deserialization", "active": True}
RULES_CATALOG["SEC-0035"] = {"id": "SEC-0035", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block __defineGetter__ function property injection", "active": True}
RULES_CATALOG["SEC-0036"] = {"id": "SEC-0036", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block __defineSetter__ function property injection", "active": True}
RULES_CATALOG["SEC-0037"] = {"id": "SEC-0037", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block __lookupGetter__ prototype traversal", "active": True}
RULES_CATALOG["SEC-0038"] = {"id": "SEC-0038", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block __lookupSetter__ prototype traversal", "active": True}
RULES_CATALOG["SEC-0039"] = {"id": "SEC-0039", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block symbol-based property pollution attempt", "active": True}
RULES_CATALOG["SEC-0040"] = {"id": "SEC-0040", "category": "prototype_pollution", "severity": "CRITICAL", "description": "block nested prototype tampering via deep path traversal", "active": True}
RULES_CATALOG["SEC-0041"] = {"id": "SEC-0041", "category": "identity_protection", "severity": "HIGH", "description": "enforce strict HMAC-SHA256 client token verification", "active": True}
