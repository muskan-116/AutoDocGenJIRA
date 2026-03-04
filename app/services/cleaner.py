import re

def clean_generated_doc(raw_doc: str, project_title: str) -> str:
    """
    Cleans the raw generated document and formats it with proper headings, bullets, and project title.
    Returns Markdown-ready text that renders properly with nested bullets.
    """
    doc = raw_doc.strip()

    # Fix repeated hashes (e.g., '# # 4. ...' -> '## 4. ...')
    doc = re.sub(r"^#+\s*#+", "##", doc, flags=re.MULTILINE)

    # Bold all headings (#, ##, ###)
    def bold_heading(match):
        hashes = match.group(1)
        title = match.group(2).strip()
        return f"{hashes} **{title}**"

    doc = re.sub(r"^(#{1,3})\s*(.+)$", bold_heading, doc, flags=re.MULTILINE)

    # Format bullets
    lines = doc.splitlines()
    formatted_lines = []
    for line in lines:
        stripped = line.lstrip()
        indent_level = (len(line) - len(stripped)) // 4  # each 4 spaces = 1 nesting level

        # Top-level bullet (no indentation)
        if indent_level == 0 and stripped.startswith("* "):
            content = stripped[2:].strip()
            # bold top-level bullet
            if content and not content.startswith("**"):
                content = f"**{content}**"
            formatted_lines.append(f"* {content}")
        # Nested bullet
        elif stripped.startswith("* "):
            content = stripped[2:].strip()
            formatted_lines.append("    " * indent_level + f"* {content}")
        else:
            formatted_lines.append(line)

    doc = "\n".join(formatted_lines)

    # Add project title at the top
    final_doc = f"# **{project_title}**\n\n{doc}"
    return final_doc
