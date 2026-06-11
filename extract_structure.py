import ast, os, sys

files = [
    'app.py', 'tor_extractor.py', 'capability_indexer.py',
    'capability_retriever.py', 'draft_generator.py',
    'citation_tagger.py', 'output_formatter.py', 'config.py',
    'tests/test_app.py', 'tests/test_capability_indexer.py',
    'tests/test_capability_retriever.py', 'tests/test_citation_tagger.py',
    'tests/test_config.py', 'tests/test_draft_generator.py',
    'tests/test_output_formatter.py', 'tests/test_tor_extractor.py',
]

lines = []
for filename in files:
    if not os.path.exists(filename):
        lines.append(f'\n=== {filename} NOT FOUND ===')
        continue
    size = os.path.getsize(filename)
    lines.append(f'\n=== {filename} ({size} bytes) ===')
    with open(filename, 'r', encoding='utf-8') as f:
        source = f.read()
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                doc = ast.get_docstring(node) or ''
                first_line = doc.split('\n')[0][:70] if doc else 'no docstring'
                lines.append(f'  def {node.name}({", ".join(args)})')
                lines.append(f'      purpose: {first_line}')
        constants = list(set([
            n.targets[0].id for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and hasattr(n.targets[0], 'id')
            and n.targets[0].id.isupper()
        ]))
        if constants:
            lines.append(f'  CONSTANTS: {", ".join(sorted(constants))}')
    except Exception as e:
        lines.append(f'  Parse error: {e}')

with open('SYSTEM_MAP_FUNCTIONS.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print('Done - saved to SYSTEM_MAP_FUNCTIONS.md')
