import requests

r = requests.get('http://localhost:5000/api/matches', params={'date': '2024-12-16'})
print(f'Status: {r.status_code}')
data = r.json()
print(f'Matches: {len(data.get("matches", []))}')
for m in data.get("matches", [])[:3]:
    print(f'  - {m.get("homeTeam")} vs {m.get("awayTeam")} ({m.get("league")})')
