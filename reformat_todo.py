import re

with open("doc/todo.md", "r", encoding="utf-8") as f:
    content = f.read()

# Replace any "#### " representing a task with "### " (except for the fast-jump list)
# We can do this by finding lines starting with "#### \d+\." and replacing with "### \d+\."
content = re.sub(r"^#### (\d+\..*)", r"### \1", content, flags=re.MULTILINE)

# Remove multiple blank lines
# Replace 3 or more newlines with exactly 2 newlines (1 blank line)
content = re.sub(r"\n{3,}", "\n\n", content)

# But before sections (## ) we want exactly 2 blank lines (3 newlines)
content = re.sub(r"\n+## ", "\n\n\n## ", content)

# And before sub-sections (### ) we want exactly 1 blank line (2 newlines)
# Note: we don't want to add extra newlines if it's right after a section header, but \n+ matches all.
# Let's just fix the ### \d+\.
content = re.sub(r"\n+### (\d+\.)", "\n\n### \1", content)

# Fix some spacing around hr
content = re.sub(r"\n+---\n+", "\n\n---\n\n", content)

# Remove trailing spaces
lines = [line.rstrip() for line in content.split("\n")]
content = "\n".join(lines) + "\n"

with open("doc/todo.md", "w", encoding="utf-8") as f:
    f.write(content)

print("Formatting done.")
