import chromadb
from config import CHROMA_DB_PATH
client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
col = client.get_collection('govrisk_capabilities')
results = col.get(limit=500, include=['metadatas'])
thematic_found = 0
geo_found = 0
for meta in results['metadatas']:
    if meta.get('thematic_areas'):
        thematic_found += 1
    if meta.get('geography'):
        geo_found += 1
print('Total sampled:', len(results['metadatas']))
print('Geography tagged:', geo_found)
print('Thematic tagged:', thematic_found)
