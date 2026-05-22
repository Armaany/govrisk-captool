from output_formatter import write_output
from citation_tagger import tag_citations
import os

draft = {
    'sections': {
        'opening_statement': 'GovRisk test. [REF:test.pdf:page_1]',
        'institutional_overview': 'Founded 2010. [REF:test.pdf:page_2]',
        'country_table': [
            {'country': 'Mexico', 'project_name': 'PECEL', 'year': '2024-2026', 'donor': 'US State Dept'},
            {'country': 'Mexico', 'project_name': 'ACROL', 'year': '2019-2022', 'donor': 'UK FCDO'},
            {'country': 'Colombia', 'project_name': 'TIFF', 'year': '2023-2024', 'donor': 'UK FCDO'}
        ],
        'geographic_experience': 'Mexico experience. [REF:test.pdf:page_3]',
        'thematic_areas': 'AML/CFT work. [REF:test.pdf:page_4]',
        'selected_project_experience': 'PECEL project. [REF:test.pdf:page_5]',
        'alignment_with_tor': 'Strong alignment. [REF:test.pdf:page_6]'
    },
    'interpretation_log': [
        {'section': 'geographic_experience', 'inference_made': 'Test',
         'source_used': 'test.pdf', 'gap_flagged': 'None', 'confidence': 'HIGH'}
    ],
    'summary': {'sections_generated': 6, 'projects_referenced': 3,
                'countries_covered': 2, 'documents_used': 1, 'overall_confidence': 'HIGH'}
}

citations = tag_citations(' '.join(str(v) for v in draft['sections'].values() if isinstance(v, str)))
sections = ['opening_statement','institutional_overview','country_table',
            'geographic_experience','thematic_areas','selected_project_experience',
            'alignment_with_tor','interpretation_log']

result = write_output(draft, citations, 'English', sections)
print('Result:', result)
print('File exists:', os.path.exists(result) if not result.startswith('ERROR') else 'ERROR returned')
