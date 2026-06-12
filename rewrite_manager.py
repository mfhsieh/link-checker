import re

with open("crawler/manager.py", "r") as f:
    content = f.read()

# 1. Remove _get_domain_delay
domain_delay_pattern = re.compile(r"def _get_domain_delay\(.*?return matched_delays\[0\]\[1\]\n", re.DOTALL)
content = domain_delay_pattern.sub("", content)

# 2. Add import for JobRunner
import_pos = content.find("from crawler.models import")
content = content[:import_pos] + "from crawler.runner import JobRunner\n" + content[import_pos:]

# 3. Remove JobRunContext dataclass
context_pattern = re.compile(r"@dataclass\nclass JobRunContext:.*?def trusted_domains_list\(self\) -> list\[str\]:\n        \"\"\"取得信任網域清單。\"\"\"\n        return self\.job\.trusted_domains\.split\(\",\"\) if self\.job\.trusted_domains else \[\]\n", re.DOTALL)
content = context_pattern.sub("", content)

# 4. Remove all private methods from _initialize_job_run to _process_queue_item
# and replace run_job with the new simple implementation.
# We can find def _initialize_job_run and def get_all_jobs
start_marker = "    def _initialize_job_run("
end_marker = "    def get_all_jobs("

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

new_run_job = """    def run_job(
        self,
        job_id: str,
        crawler_config: dict[str, object] | None = None,
        force: bool = False,
    ) -> None:
        \"\"\"
        執行指定的爬蟲任務，直到佇列清空或遭到使用者中斷為止。

        Args:
            job_id (str): 欲執行的任務 ID。
            crawler_config (dict[str, object] | None): 爬蟲相關的設定參數。
            force (bool): 是否強制接管卡在 running 狀態的任務。
        \"\"\"
        runner = JobRunner(self.session_factory, job_id)
        runner.execute(crawler_config, force)

"""

if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + new_run_job + content[end_idx:]

with open("crawler/manager.py", "w") as f:
    f.write(content)
