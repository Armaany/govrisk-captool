import re, json
from draft_generator import _strip_markdown_fences

# Simulate exact Claude response
fake = '`' + 'json\n{"sections": {"opening_statement": "test"}, "interpretation_log": [], "summary": {"sections_generated": 1, "projects_referenced": 0, "countries_covered": 0, "documents_used": 0, "overall_confidence": "HIGH"}}\n`' + ''

print('Input starts with:', repr(fake[:30]))
cleaned = _strip_markdown_fences(fake)
print('Cleaned starts with:', repr(cleaned[:30]))

try:
    parsed = json.loads(cleaned)
    print('JSON PARSE: SUCCESS')
except Exception as e:
    print('JSON PARSE FAILED:', e)
