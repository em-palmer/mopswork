"""Check results with Adzuna."""
import httpx, json

r = httpx.get("http://localhost:8003/api/stats", timeout=10)
print("STATS:", json.dumps(r.json(), indent=2))

r = httpx.get("http://localhost:8003/api/jobs?source=adzuna&min_score=0&limit=50", timeout=10)
jobs = r.json()
print(f"\nAdzuna jobs found: {len(jobs)}")
for j in jobs[:5]:
    print(f"  [{j['match_score']}] {j['title']} @ {j['company']} - {j['location']}")

r = httpx.get("http://localhost:8003/api/jobs?min_score=10&limit=10", timeout=10)
top = r.json()
print(f"\n--- Top 10 overall ---")
for j in top[:10]:
    print(f"  [{j['match_score']}] {j['source']}: {j['title']} @ {j['company']}")