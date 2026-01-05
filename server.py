#!/usr/bin/env python3
"""Aigon Viewer - Lightweight FastAPI markdown viewer for local files"""

from pathlib import Path
from datetime import datetime
import os
from typing import List, Dict, Any, Optional
import hashlib
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import markdown
from markdown.extensions import fenced_code, tables, nl2br, sane_lists, codehilite, meta, toc
import aiofiles
import uvicorn
import httpx
import asyncio
import urllib.parse

# Import version information
try:
    from .version import __version__ as APP_VERSION
except ImportError:
    # Fallback for when running as script directly
    from version import __version__ as APP_VERSION

# Configuration
FILEDB_FILE_DIR = None  # Will be set by command line arguments or environment
REFRESH_INTERVAL = 30  # seconds
CONFIG_FILE = Path(__file__).parent / "config.toml"
CACHE_DIR = None  # Will be set based on FILEDB_FILE_DIR
CACHE_EXPIRY = 300  # 5 minutes for remote file cache
LOCAL_ONLY_MODE = os.getenv("FILEDB_LOCAL_ONLY", "true").lower() == "true"

# Check for environment variable on module load
if os.environ.get("FILEDB_SERVE_DIR"):
    FILEDB_FILE_DIR = Path(os.environ["FILEDB_SERVE_DIR"]).resolve()
    CACHE_DIR = FILEDB_FILE_DIR / ".remote-cache"
    CACHE_DIR.mkdir(exist_ok=True, parents=True)

def clear_cache():
    """Clear all cached files"""
    import shutil
    if CACHE_DIR and CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        CACHE_DIR.mkdir(exist_ok=True)
        print(f"Cache cleared: {CACHE_DIR}")

app = FastAPI(title="Aigon Viewer")

# Setup templates and static files
templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"

# Create directories if they don't exist
templates_dir.mkdir(exist_ok=True)
static_dir.mkdir(exist_ok=True)

# Setup Jinja2 templates
templates = Jinja2Templates(directory=str(templates_dir))

# Mount static files
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Configure markdown processor with extensions
try:
    import pymdownx.tilde
    # Use pymdownx extensions if available for enhanced features
    md = markdown.Markdown(
        extensions=[
            'markdown.extensions.fenced_code',
            'markdown.extensions.tables',
            'markdown.extensions.nl2br',
            'markdown.extensions.sane_lists',
            'markdown.extensions.codehilite',
            'markdown.extensions.meta',
            'markdown.extensions.toc',
            'markdown.extensions.def_list',
            'markdown.extensions.abbr',
            'markdown.extensions.attr_list',
            'markdown.extensions.footnotes',
            'markdown.extensions.md_in_html',
            'markdown.extensions.admonition',
            'markdown.extensions.legacy_em',
            'markdown.extensions.smarty',
            'markdown.extensions.wikilinks',
            'pymdownx.tilde',  # For strikethrough
            'pymdownx.emoji',  # For emoji support
            'pymdownx.superfences',
            'pymdownx.inlinehilite',
        ],
        extension_configs={
            'markdown.extensions.codehilite': {
                'use_pygments': True,
                'css_class': 'highlight',
                'linenums': False,
                'guess_lang': True,
                'noclasses': False,
            }
        }
    )
except ImportError:
    # Fallback without pymdownx but with proper codehilite configuration
    md = markdown.Markdown(
        extensions=[
            'markdown.extensions.fenced_code',
            'markdown.extensions.tables',
            'markdown.extensions.nl2br',
            'markdown.extensions.sane_lists',
            'markdown.extensions.codehilite',
            'markdown.extensions.meta',
            'markdown.extensions.toc',
            'markdown.extensions.def_list',
            'markdown.extensions.abbr',
            'markdown.extensions.attr_list',
            'markdown.extensions.footnotes',
            'markdown.extensions.md_in_html',
            'markdown.extensions.admonition',
            'markdown.extensions.legacy_em',
            'markdown.extensions.smarty',
            'markdown.extensions.wikilinks',
        ],
        extension_configs={
            'markdown.extensions.codehilite': {
                'use_pygments': True,
                'css_class': 'highlight',
                'linenums': False,
                'guess_lang': True,
                'noclasses': False,
            }
        }
    )

def get_file_info(filepath: Path) -> Dict[str, Any]:
    """Get file metadata"""
    stat = filepath.stat()
    return {
        "name": filepath.name,
        "size": stat.st_size,
        "size_human": format_size(stat.st_size),
        "modified": stat.st_mtime,
        "modified_human": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    }

def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def process_mermaid_blocks(content: str) -> str:
    """Convert mermaid code blocks to div elements for client-side rendering"""
    import re

    # Pattern to match mermaid code blocks
    pattern = r'```mermaid\n(.*?)\n```'

    def replace_mermaid(match):
        mermaid_code = match.group(1)
        return f'<div class="mermaid">\n{mermaid_code}\n</div>'

    return re.sub(pattern, replace_mermaid, content, flags=re.DOTALL)

def ensure_list_newlines(content: str) -> str:
    """Ensure lists have blank lines before them for proper markdown rendering

    Adds a blank line before:
    - Unordered lists (lines starting with -, *, +)
    - Ordered lists (lines starting with digit(s) followed by . or ))

    But only if the previous line is not already blank and not part of a list.
    """
    import re

    lines = content.split('\n')
    result = []

    for i, line in enumerate(lines):
        # Check if current line starts a list
        is_list_start = bool(re.match(r'^\s*[-*+]\s+', line) or re.match(r'^\s*\d+[.)]\s+', line))

        if is_list_start and i > 0:
            prev_line = lines[i-1].strip()
            # Add blank line if previous line is not blank and not a list item
            if prev_line and not re.match(r'^[-*+]\s+', prev_line) and not re.match(r'^\d+[.)]\s+', prev_line):
                result.append('')  # Add blank line

        result.append(line)

    return '\n'.join(result)

def yaml_meta_to_html_table(yaml_meta: dict) -> str:
    """Convert YAML front matter to HTML table

    Args:
        yaml_meta: Dictionary of front matter key-value pairs

    Returns:
        HTML table string with formatted front matter

    Formatting rules:
        - Lists: rendered as <ul><li> bulleted lists
        - Dicts: rendered as <ul><li>key: str(value)</li> bulleted lists
        - Others: plain text
    """
    if not yaml_meta:
        return ""

    html_parts = ['<table class="frontmatter-table">\n']

    for key, value in yaml_meta.items():
        html_parts.append(f'<tr><th>{key}</th><td>')

        if isinstance(value, list):
            # Render list as bulleted list
            html_parts.append('<ul>')
            for item in value:
                html_parts.append(f'<li>{str(item)}</li>')
            html_parts.append('</ul>')
        elif isinstance(value, dict):
            # Render dict as bulleted list with key: value
            html_parts.append('<ul>')
            for k, v in value.items():
                html_parts.append(f'<li>{k}: {str(v)}</li>')
            html_parts.append('</ul>')
        else:
            # Plain text
            html_parts.append(str(value))

        html_parts.append('</td></tr>\n')

    html_parts.append('</table>\n')
    return ''.join(html_parts)

def load_configurations() -> Dict[str, List[str]]:
    """Load configurations from simple text file - local files only"""
    # Look for _config.toml in the directory being served (FILEDB_FILE_DIR), not in app directory
    config_file = FILEDB_FILE_DIR / "_config.toml" if FILEDB_FILE_DIR else CONFIG_FILE
    if not config_file.exists():
        return {}

    try:
        configurations = {}
        current_section = None

        with open(config_file, 'r') as f:
            for line in f:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue

                # Check if it's a section header
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                    configurations[current_section] = []
                elif current_section:
                    # Add file to current section
                    configurations[current_section].append(line)

        return configurations
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

async def get_aigon_files() -> Dict[str, str]:
    """Get list of files from Aigon API"""
    if LOCAL_ONLY_MODE:
        return {}

    token = os.getenv("AIGON_API_TOKEN")
    if not token:
        print("AIGON_API_TOKEN not set, no Aigon files available")
        return {}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.aigon.ai/filedb/files",
                headers={"Authorization": f"Bearer {token}"},
                params={"namespace": "user/"}
            )
            response.raise_for_status()
            data = response.json()

            aigon_files = {}
            for file_info in data.get("files", []):
                basename = file_info.get("basename")
                if basename:
                    aigon_files[basename] = f"aigon:{basename}"

            print(f"Found {len(aigon_files)} files in Aigon API: {list(aigon_files.keys())}")
            return aigon_files
    except Exception as e:
        print(f"Error fetching Aigon files: {e}")
        return {}

def load_remote_urls() -> Dict[str, str]:
    """Load remote URL mappings for files - filename -> URL"""
    if LOCAL_ONLY_MODE:
        return {}

    remote_file = Path(__file__).parent / "remote_urls.txt"

    urls = {}

    # Load manual mappings if file exists
    if remote_file.exists():
        try:
            with open(remote_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()

                    if not line or line.startswith('#'):
                        continue

                    # Format: filename=url
                    if '=' in line:
                        filename, url = line.split('=', 1)
                        filename = filename.strip()
                        url = url.strip()
                        urls[filename] = url

            print(f"Loaded {len(urls)} manual remote URL mappings")
        except Exception as e:
            print(f"Error loading remote URLs: {e}")

    return urls

async def get_all_remote_urls() -> Dict[str, str]:
    """Get all remote URLs - both manual mappings and Aigon files"""
    if LOCAL_ONLY_MODE:
        return {}

    manual_urls = load_remote_urls()
    aigon_files = await get_aigon_files()

    # Combine manual URLs and Aigon files (manual takes precedence)
    all_urls = {**aigon_files, **manual_urls}

    print(f"Total remote URLs: {len(all_urls)} (manual: {len(manual_urls)}, aigon: {len(aigon_files)})")
    return all_urls

async def fetch_remote_file(url_or_spec: str, version: Optional[int] = None) -> Optional[str]:
    """Fetch content from remote URL or Aigon API with caching"""
    # Include version in cache key if specified
    cache_key_input = f"{url_or_spec}:v{version}" if version else url_or_spec
    cache_key = hashlib.md5(cache_key_input.encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.md"

    # Check if cached file exists and is not expired
    if cache_file.exists():
        cache_time = cache_file.stat().st_mtime
        if time.time() - cache_time < CACHE_EXPIRY:
            async with aiofiles.open(cache_file, 'r', encoding='utf-8') as f:
                return await f.read()

    content = None

    try:
        if url_or_spec.startswith("aigon:"):
            # Fetch from Aigon API
            basename = url_or_spec[6:]  # Remove "aigon:" prefix
            print(f"Fetching Aigon file: {basename} (version: {version or 'latest'})")

            # Get token from environment
            token = os.getenv("AIGON_API_TOKEN")
            if not token:
                print("AIGON_API_TOKEN environment variable not set")
                return None

            url = f"https://api.aigon.ai/filedb/files/{basename}"
            headers = {"Authorization": f"Bearer {token}"}
            params = {"namespace": "user/"}

            # Add version parameter if specified
            if version is not None:
                params["version"] = version


            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers, params=params)

                if response.status_code != 200:
                    print(f"Response text: {response.text}")
                    response.raise_for_status()

                data = response.json()

                # Extract content from the nested structure
                if "file_info" in data and "content" in data["file_info"]:
                    content = data["file_info"]["content"]
                    # Also extract version info if available
                    file_version = data["file_info"].get("version", "unknown")
                    print(f"Retrieved version: {file_version}")
                else:
                    content = data.get("content", "")

        else:
            # Regular URL fetch
            print(f"Fetching regular URL: {url_or_spec}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url_or_spec)
                response.raise_for_status()
                content = response.text

        if content is not None:
            # Cache the content
            async with aiofiles.open(cache_file, 'w', encoding='utf-8') as f:
                await f.write(content)
            print(f"Cached content ({len(content)} chars) to: {cache_file}")

        return content
    except Exception as e:
        print(f"Error fetching {url_or_spec}: {e}")
        import traceback
        traceback.print_exc()
        # Try to return cached version even if expired
        if cache_file.exists():
            async with aiofiles.open(cache_file, 'r', encoding='utf-8') as f:
                return await f.read()
        return None

def get_url_info(url: str) -> Dict[str, Any]:
    """Get URL metadata"""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.md"

    # Use cache file stats if available
    if cache_file.exists():
        stat = cache_file.stat()
        return {
            "name": url.split('/')[-1] or url,
            "url": url,
            "size": stat.st_size,
            "size_human": format_size(stat.st_size),
            "modified": stat.st_mtime,
            "modified_human": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "cached": True
        }
    else:
        return {
            "name": url.split('/')[-1] or url,
            "url": url,
            "size": 0,
            "size_human": "Unknown",
            "modified": 0,
            "modified_human": "Not cached",
            "cached": False
        }

def get_file_configurations(filename: str) -> List[str]:
    """Get list of configurations a file belongs to"""
    configs = load_configurations()
    file_configs = []

    # Remove .md extension if present
    filename_base = filename.replace('.md', '')

    for config_name, files in configs.items():
        if filename_base in files:
            file_configs.append(config_name)

    return file_configs

async def get_markdown_files() -> List[Dict[str, Any]]:
    """Get list of markdown files in parent directory"""
    if FILEDB_FILE_DIR is None:
        return []

    files = []
    configs = load_configurations()
    remote_urls = await get_all_remote_urls()

    print(f"Configurations: {configs}")
    print(f"Remote URLs: {remote_urls}")

    # Get all files that are in any configuration
    configured_files = set()
    for file_list in configs.values():
        configured_files.update(file_list)

    print(f"Configured files: {configured_files}")

    for filepath in sorted(FILEDB_FILE_DIR.glob("*.md")):
        if filepath.is_file():
            file_info = get_file_info(filepath)
            filename_base = filepath.stem

            # Add configuration info
            file_info['configurations'] = get_file_configurations(filepath.name)
            file_info['is_configured'] = filename_base in configured_files
            file_info['has_remote'] = filename_base in remote_urls

            print(f"File: {filepath.name}, base: {filename_base}, has_remote: {file_info['has_remote']}")

            files.append(file_info)

    print(f"Total files found: {len(files)}")
    return files

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, config: str = None, source: str = "local"):
    """Directory listing page"""
    all_files = await get_markdown_files()
    configurations = load_configurations()

    # Add automatic "Unconfigured" group (only if there are existing configurations)
    if configurations:
        configured_files = set()
        for file_list in configurations.values():
            configured_files.update(file_list)

        unconfigured_files = [f['name'].replace('.md', '') for f in all_files
                              if f['name'].replace('.md', '') not in configured_files]

        if unconfigured_files:
            configurations['Unconfigured'] = unconfigured_files

    # Filter files based on source
    if source == "remote":
        # Show all files that have remote sources configured
        remote_urls = await get_all_remote_urls()
        files = []

        # Add files that exist locally AND have remote sources
        for f in all_files:
            if f['has_remote']:
                files.append(f)

        # Add files that only exist remotely (in remote_urls but not locally)
        for filename_base, url in remote_urls.items():
            filename_md = f"{filename_base}.md"
            # Check if this file is already in our list
            if not any(f['name'] == filename_md for f in files):
                # Create a virtual file entry for remote-only file
                remote_file = {
                    'name': filename_md,
                    'size': 0,
                    'size_human': 'Remote',
                    'modified': 0,
                    'modified_human': 'Remote file',
                    'configurations': get_file_configurations(filename_md),
                    'is_configured': True,
                    'has_remote': True
                }
                files.append(remote_file)

        print(f"Showing {len(files)} remote files (includes remote-only files)")
    else:
        files = all_files

    # Filter files if a configuration is selected
    if config:
        # URL-decode the config parameter
        config = urllib.parse.unquote(config)
        if config in configurations:
            config_files = configurations[config]
            files = [f for f in files if f['name'].replace('.md', '') in config_files]

    print(f"Final file count: {len(files)}")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "files": files,
            "configurations": configurations,
            "selected_config": config,
            "selected_source": source,
            "refresh_interval": REFRESH_INTERVAL,
            "app_version": APP_VERSION,
            "local_only": LOCAL_ONLY_MODE
        }
    )

async def get_file_versions(basename: str) -> List[Dict[str, Any]]:
    """Get list of available versions for an Aigon file"""
    token = os.getenv("AIGON_API_TOKEN")
    if not token:
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get file info which should include version history
            response = await client.get(
                f"https://api.aigon.ai/filedb/files/{basename}",
                headers={"Authorization": f"Bearer {token}"},
                params={"namespace": "user/"}
            )
            response.raise_for_status()
            data = response.json()

            versions = []
            if "file_info" in data:
                file_info = data["file_info"]
                current_version = file_info.get("version", 1)

                # Create a list from current version down to 1 (reverse order)
                for v in range(current_version, 0, -1):
                    versions.append({
                        "version": v,
                        "is_current": v == current_version
                    })

            return versions
    except Exception as e:
        print(f"Error getting versions for {basename}: {e}")
        return []

@app.get("/view/{filename}", response_class=HTMLResponse)
async def view_file(request: Request, filename: str, source: str = "local", version: Optional[int] = None):
    """View markdown file - from local disk or remote URL"""
    if not filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="Only markdown files are supported")

    content = None
    file_info = None

    if source == "remote":
        # Get remote URL for this filename
        remote_urls = await get_all_remote_urls()
        filename_base = filename.replace('.md', '')


        if filename_base not in remote_urls:
            raise HTTPException(status_code=404, detail="Remote URL not configured for this file")

        url = remote_urls[filename_base]

        content = await fetch_remote_file(url, version)


        if content is None:
            raise HTTPException(status_code=404, detail="Could not fetch remote file")

        file_info = get_url_info(url)
        file_info['name'] = filename
    else:
        # Local file
        filepath = FILEDB_FILE_DIR / filename

        if not filepath.exists() or not filepath.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        # Read file content
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            content = await f.read()

        file_info = get_file_info(filepath)

    # Extract and remove YAML front matter before processing
    import re
    yaml_meta = {}

    # Check for YAML front matter at the start of the document
    # Pattern: line with 3+ dashes at column 0, content, line with 3+ dashes at column 0
    # The ^ anchor with re.MULTILINE ensures dashes must be at start of line
    # This prevents lines like "  - item" from being treated as delimiters
    yaml_pattern = r'^-{3,}\s*\n(.*?)\n^-{3,}\s*\n'
    yaml_match = re.match(yaml_pattern, content, re.DOTALL | re.MULTILINE)

    if yaml_match:
        yaml_content = yaml_match.group(1)
        # Remove YAML front matter from content (entire match including delimiters)
        content = content[yaml_match.end():]

        # Parse YAML if possible
        try:
            import yaml
            yaml_meta = yaml.safe_load(yaml_content)
        except (ImportError, Exception):
            # Fallback to empty if PyYAML not available or parsing fails
            yaml_meta = {}

    # Ensure lists have proper blank lines before them
    content = ensure_list_newlines(content)

    # Process mermaid blocks before markdown conversion
    content = process_mermaid_blocks(content)

    # Convert markdown to HTML (without YAML front matter)
    html_content = md.convert(content)

    # Also get metadata from meta extension if available (backup)
    if not yaml_meta and hasattr(md, 'Meta'):
        yaml_meta = md.Meta

    # Extract headings for TOC
    import re
    from html import unescape

    def extract_headings(html):
        heading_pattern = r'<h([1-6])([^>]*)>(.*?)</h[1-6]>'
        headings = []
        for match in re.finditer(heading_pattern, html, re.IGNORECASE | re.DOTALL):
            level = int(match.group(1))
            # Only include h2 headings
            if level != 2:
                continue
            attrs = match.group(2)
            text = unescape(re.sub(r'<[^>]+>', '', match.group(3))).strip()

            # Extract or generate ID
            id_match = re.search(r'id=["\']([^"\']+)["\']', attrs)
            if id_match:
                heading_id = id_match.group(1)
            else:
                # Generate ID from text
                heading_id = re.sub(r'[^\w\s-]', '', text.lower()).replace(' ', '-')
                heading_id = re.sub(r'-+', '-', heading_id).strip('-')

            headings.append({
                'level': level,
                'id': heading_id,
                'text': text
            })
        return headings

    toc_headings = extract_headings(html_content)

    # Get available versions if this is a remote Aigon file
    versions = []
    if source == "remote" and url.startswith("aigon:"):
        versions = await get_file_versions(filename_base)

    return templates.TemplateResponse(
        "viewer.html",
        {
            "request": request,
            "filename": filename,
            "file_info": file_info,
            "content": html_content,
            "source": source,
            "version": version,
            "versions": versions,
            "toc_headings": toc_headings,
            "yaml_meta": yaml_meta,
            "refresh_interval": REFRESH_INTERVAL,
            "app_version": APP_VERSION,
            "local_only": LOCAL_ONLY_MODE
        }
    )

@app.get("/api/files", response_class=JSONResponse)
async def api_files():
    """API endpoint to get list of files"""
    files = await get_markdown_files()
    return JSONResponse(content=files)

@app.get("/api/file/{filename}/info", response_class=JSONResponse)
async def api_file_info(filename: str):
    """API endpoint to get file metadata"""
    filepath = FILEDB_FILE_DIR / filename

    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return JSONResponse(content=get_file_info(filepath))

@app.get("/api/file/{filename}/content", response_class=JSONResponse)
async def api_file_content(filename: str, source: str = "local"):
    """API endpoint to get rendered markdown content"""
    if source == "remote":
        # Get remote content
        remote_urls = await get_all_remote_urls()
        filename_base = filename.replace('.md', '')

        if filename_base not in remote_urls:
            raise HTTPException(status_code=404, detail="Remote URL not configured for this file")

        url = remote_urls[filename_base]
        content = await fetch_remote_file(url)

        if content is None:
            raise HTTPException(status_code=404, detail="Could not fetch remote file")

        # Ensure lists have proper blank lines before them
        content = ensure_list_newlines(content)

        # Process mermaid blocks before markdown conversion
        content = process_mermaid_blocks(content)

        # Convert markdown to HTML
        html_content = md.convert(content)

        # Use current time as modified time for remote files
        import time
        return JSONResponse(content={
            "html": html_content,
            "modified": time.time()
        })
    else:
        # Local file
        filepath = FILEDB_FILE_DIR / filename

        if not filepath.exists() or not filepath.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        # Read file content
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            content = await f.read()

        # Ensure lists have proper blank lines before them
        content = ensure_list_newlines(content)

        # Process mermaid blocks before markdown conversion
        content = process_mermaid_blocks(content)

        # Convert markdown to HTML
        html_content = md.convert(content)

        return JSONResponse(content={
            "html": html_content,
            "modified": filepath.stat().st_mtime
        })

@app.get("/api/file/{filename}/markdown", response_class=JSONResponse)
async def api_file_markdown(filename: str, source: str = "local", version: Optional[int] = None):
    """API endpoint to get raw markdown content"""
    if source == "remote":
        # Get remote content
        remote_urls = await get_all_remote_urls()
        filename_base = filename.replace('.md', '')

        if filename_base not in remote_urls:
            raise HTTPException(status_code=404, detail="Remote URL not configured for this file")

        url = remote_urls[filename_base]
        content = await fetch_remote_file(url, version)

        if content is None:
            raise HTTPException(status_code=404, detail="Could not fetch remote file")

        # Use current time as modified time for remote files
        import time
        return JSONResponse(content={
            "markdown": content,
            "modified": time.time()
        })
    else:
        # Local file
        filepath = FILEDB_FILE_DIR / filename

        if not filepath.exists() or not filepath.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        # Read file content
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            content = await f.read()

        return JSONResponse(content={
            "markdown": content,
            "modified": filepath.stat().st_mtime
        })

@app.get("/api/file/{filename}/html", response_class=JSONResponse)
async def api_file_html(filename: str, source: str = "local", version: Optional[int] = None):
    """API endpoint to get HTML content with front matter table

    Returns:
        JSON with frontmatter_html and content_html fields
    """
    if source == "remote":
        # Get remote content
        remote_urls = await get_all_remote_urls()
        filename_base = filename.replace('.md', '')

        if filename_base not in remote_urls:
            raise HTTPException(status_code=404, detail="Remote URL not configured for this file")

        url = remote_urls[filename_base]
        content = await fetch_remote_file(url, version)

        if content is None:
            raise HTTPException(status_code=404, detail="Could not fetch remote file")

        # Use current time as modified time for remote files
        import time
        modified_time = time.time()
    else:
        # Local file
        filepath = FILEDB_FILE_DIR / filename

        if not filepath.exists() or not filepath.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        # Read file content
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            content = await f.read()

        modified_time = filepath.stat().st_mtime

    # Extract and remove YAML front matter
    import re
    yaml_meta = {}

    # Check for YAML front matter at the start of the document
    yaml_pattern = r'^-{3,}\s*\n(.*?)\n^-{3,}\s*\n'
    yaml_match = re.match(yaml_pattern, content, re.DOTALL | re.MULTILINE)

    if yaml_match:
        yaml_content = yaml_match.group(1)
        # Remove YAML front matter from content
        content = content[yaml_match.end():]

        # Parse YAML if possible
        try:
            import yaml
            yaml_meta = yaml.safe_load(yaml_content)
        except (ImportError, Exception):
            yaml_meta = {}

    # Generate front matter HTML table
    frontmatter_html = yaml_meta_to_html_table(yaml_meta)

    # Ensure lists have proper blank lines before them
    content = ensure_list_newlines(content)

    # Process mermaid blocks before markdown conversion
    content = process_mermaid_blocks(content)

    # Convert markdown to HTML
    content_html = md.convert(content)

    return JSONResponse(content={
        "frontmatter_html": frontmatter_html,
        "content_html": content_html,
        "modified": modified_time
    })

@app.post("/api/cache/clear")
async def clear_cache_endpoint():
    """API endpoint to manually clear cache"""
    clear_cache()
    return JSONResponse(content={"success": True, "message": "Cache cleared successfully"})

@app.get("/api/cache/status")
async def cache_status():
    """Get cache status and file count"""
    if not CACHE_DIR.exists():
        return JSONResponse(content={"files": 0, "size": "0 B"})

    cache_files = list(CACHE_DIR.glob("*.md"))
    total_size = sum(f.stat().st_size for f in cache_files)

    # Format size
    size_str = format_size(total_size)

    return JSONResponse(content={
        "files": len(cache_files),
        "size": size_str,
        "expiry_minutes": CACHE_EXPIRY // 60
    })

def initialize_directories(directory: str):
    """Initialize global directory variables"""
    global FILEDB_FILE_DIR, CACHE_DIR
    FILEDB_FILE_DIR = Path(directory).resolve()
    CACHE_DIR = FILEDB_FILE_DIR / ".remote-cache"

    # Create cache directory with new path (create parent directories if needed)
    CACHE_DIR.mkdir(exist_ok=True, parents=True)
    clear_cache()

    print(f"📁 Serving markdown files from: {FILEDB_FILE_DIR}")
    print(f"💾 Cache directory: {CACHE_DIR}")

    # Check for _config.toml in the served directory
    config_file = FILEDB_FILE_DIR / "_config.toml"
    if config_file.exists():
        print(f"📋 Config file found: {config_file}")
        configs = load_configurations()
        if configs:
            print(f"📚 Categories loaded from _config.toml:")
            for category, files in configs.items():
                print(f"   - {category}: {len(files)} files")
        else:
            print("   ⚠️  Config file is empty or invalid")
    else:
        print(f"📋 No _config.toml found in {FILEDB_FILE_DIR}")

    # List markdown files found
    md_files = list(FILEDB_FILE_DIR.glob("*.md"))
    if md_files:
        print(f"📄 Found {len(md_files)} markdown files:")
        for file in sorted(md_files)[:10]:  # Show first 10
            print(f"   - {file.name}")
        if len(md_files) > 10:
            print(f"   ... and {len(md_files) - 10} more")
    else:
        print("⚠️  No markdown files found in the directory")

def open_browser(url, delay=1.5):
    """Open browser after a short delay to ensure server is ready."""
    import time
    import webbrowser
    time.sleep(delay)
    webbrowser.open(url)

def main():
    """Main entry point for the server."""
    import argparse
    import threading

    parser = argparse.ArgumentParser(
        description="Aigon Viewer Server - Lightweight FastAPI markdown viewer for local files",
        epilog="GitHub: https://github.com/aigonai/aigonviewer"
    )
    parser.add_argument("--version", "-v", action="version",
                        version=f"aigonviewer {APP_VERSION}")
    parser.add_argument("path", nargs="?", type=str,
                        help="Directory to serve markdown files from (default: current directory)")
    parser.add_argument("--directory", "-d", type=str,
                        help=argparse.SUPPRESS)  # Hidden for backwards compatibility
    parser.add_argument("--port", "-p", type=int, default=3030,
                        help="Port to run the server on (default: 3030)")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--remote", action="store_true",
                        help="Enable remote sources (Aigon API, URLs)")
    parser.add_argument("--local-only", action="store_true",
                        help=argparse.SUPPRESS)  # Hidden - default is local-only
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't automatically open browser")

    args = parser.parse_args()

    # Determine directory: positional > --directory > current directory
    if args.path and args.directory:
        parser.error("Cannot specify both positional directory and --directory flag")
    elif args.path:
        directory = args.path
    elif args.directory:
        directory = args.directory
    else:
        directory = "."

    # Set environment variables for uvicorn subprocess
    os.environ["FILEDB_SERVE_DIR"] = directory
    # Default is local-only unless --remote is specified
    if args.remote:
        os.environ["FILEDB_LOCAL_ONLY"] = "false"
        print("🌐 Running with REMOTE sources enabled (Aigon API, URLs)")
    else:
        os.environ["FILEDB_LOCAL_ONLY"] = "true"
        print("🏠 Running in LOCAL-ONLY mode (remote features disabled)")

    initialize_directories(directory)

    url = f"http://{args.host}:{args.port}"
    print(f"Server starting on {url}")

    # Open browser in background thread (unless --no-browser)
    if not args.no_browser:
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    uvicorn.run("server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()