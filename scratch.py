import sys
from backend.models import DBSession, Job, CrawlQueue, Link
db = DBSession()
job_a = "ee794e47-8065-41e7-9ef5-d18c8691f716"
job_b = "e0199aef-fd14-41d8-93d6-f56903d2cdab"
url = "https://www.mac.gov.tw/DO/DownloadController.Attach.asp?xpath=public/Attachment/482111175074.pdf"

print("--- EXTERNAL LINKS ---")
link_a = db.query(Link).filter(Link.job_id == job_a, Link.target_url == url).first()
if link_a:
    print(f"Job A Link: status={link_a.status_code}, error={link_a.error_message}, secure={link_a.is_secure}")
else:
    print("Job A Link: None")

link_b = db.query(Link).filter(Link.job_id == job_b, Link.target_url == url).first()
if link_b:
    print(f"Job B Link: status={link_b.status_code}, error={link_b.error_message}, secure={link_b.is_secure}")
else:
    print("Job B Link: None")

print("\n--- INTERNAL LINKS ---")
cq_a = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_a, CrawlQueue.url == url).first()
if cq_a:
    print(f"Job A CQ: status={cq_a.status_code}, error={cq_a.error_message}")
else:
    print("Job A CQ: None")
    
cq_b = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_b, CrawlQueue.url == url).first()
if cq_b:
    print(f"Job B CQ: status={cq_b.status_code}, error={cq_b.error_message}")
else:
    print("Job B CQ: None")

