import sys
import re

with open("crawler/manager.py", "r") as f:
    content = f.read()

# 1. Fix JobRunContext properties
pattern_ctx = re.compile(r"    crawled_count: int\n    target_domains_list: list\[str\]\n    trusted_domains_list: list\[str\]\n")
replacement_ctx = """    crawled_count: int

    @property
    def target_domains_list(self) -> list[str]:
        return self.job.target_domains.split(",") if self.job.target_domains else []

    @property
    def trusted_domains_list(self) -> list[str]:
        return self.job.trusted_domains.split(",") if self.job.trusted_domains else []
"""
content = pattern_ctx.sub(replacement_ctx, content)

# 2. Extract _process_unchecked_external_links
pattern_extract = re.compile(r"        if links_needing_http_check:.*?                    ctx\.session\.add\(new_ext\)\n", re.DOTALL)
replacement_extract = """        if links_needing_http_check:
            self._process_unchecked_external_links(ctx, current_url, links_needing_http_check)

    def _process_unchecked_external_links(self, ctx: JobRunContext, current_url: str, links_needing_http_check: list[str]) -> None:
        def check_single_link(ext_link: str) -> tuple[str, str | None, int | None, str | None]:
            tgt_dom = get_domain(ext_link)
            ip_res = resolve_ip(tgt_dom) if tgt_dom else None
            code_res, err_res = ctx.crawler.check_external_link(ext_link)
            return ext_link, ip_res, code_res, err_res

        results = list(ctx.executor.map(check_single_link, links_needing_http_check))

        for link, ip, status_code, err_msg in results:
            ctx.checked_links_cache[link] = (ip, status_code, err_msg)
            exists = (
                ctx.session.query(ExternalLink)
                .filter(
                    ExternalLink.job_id == ctx.job.id,
                    ExternalLink.source_url == current_url,
                    ExternalLink.target_url == link,
                )
                .first()
            )
            if not exists:
                is_sec = link.startswith("https://")
                new_ext = ExternalLink(
                    job_id=ctx.job.id,
                    source_url=current_url,
                    target_url=link,
                    ip_address=ip,
                    is_secure=is_sec,
                    http_status_code=status_code,
                    error_message=err_msg,
                )
                ctx.session.add(new_ext)\n"""
content = pattern_extract.sub(replacement_extract, content)

# Also fix the _build_run_context so it doesn't initialize target_domains_list anymore
content = content.replace("            target_domains_list=target_domains_list,\n            trusted_domains_list=trusted_domains_list,\n", "")
content = content.replace('        target_domains_list: list[str] = job.target_domains.split(",") if job.target_domains else []\n        trusted_domains_list: list[str] = job.trusted_domains.split(",") if job.trusted_domains else []\n\n', "")

with open("crawler/manager.py", "w") as f:
    f.write(content)
