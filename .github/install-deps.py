#!/usr/bin/env python3
"""Install all git deps from hmm.json via GitHub tarball + haxelib dev.

Reason: haxelib git uses a shallow clone (--depth 1) which can only
checkout the repo HEAD. hmm.json pins specific commits that are NOT
HEAD for some repos (hxcpp, lime, ...), so `haxelib git` fails with
"Could not checkout branch, tag or path".

Tarball download works for ANY commit SHA and avoids git protocol.
This script:
1. Reads hmm.json
2. Removes all git deps from it (so hmm only installs haxelib deps)
3. Downloads each git dep tarball, extracts, and `haxelib dev`s it
"""
import json, os, subprocess, urllib.request, tarfile, shutil, sys

MODE = sys.argv[1] if len(sys.argv) > 1 else 'all'
BASE = '/tmp/haxelib-deps'
os.makedirs(BASE, exist_ok=True)

with open('hmm.json') as f:
    data = json.load(f)

deps = data['dependencies']
git_deps = [d for d in deps if d.get('type') == 'git']

DEPS_CACHE = os.path.join(BASE, 'git_deps.json')

def load_git_deps():
    """prepare() strips git deps from hmm.json, so dev() can't see them.
    Cache the list on disk during prepare and prefer it here."""
    if os.path.exists(DEPS_CACHE):
        with open(DEPS_CACHE) as f:
            return json.load(f)
    with open('hmm.json') as f:
        data = json.load(f)
    return [d for d in data['dependencies'] if d.get('type') == 'git']

def download(url, dest):
    req = urllib.request.Request(url, headers={'User-Agent': 'WorkBuddy-CI'})
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f)

def extract(tgz, target):
    with tarfile.open(tgz, 'r:gz') as t:
        for m in t.getmembers():
            parts = m.name.split('/', 1)
            m.name = parts[1] if len(parts) == 2 else parts[0]
        t.extractall(target, filter='data')

def fetch_all():
    for dep in git_deps:
        name = dep['name']
        target = os.path.join(BASE, name)
        if os.path.isdir(target) and os.listdir(target):
            print(f'== {name}: already present, skip', flush=True)
            continue
        ref = dep['ref']
        url = dep['url'].rstrip('/').removesuffix('.git')
        if not url.startswith('http'):
            url = 'https://github.com/' + url
        repo_path = url.replace('https://github.com/', '').replace('http://github.com/', '')
        tgz = os.path.join(BASE, name + '.tar.gz')
        dl_url = f'https://codeload.github.com/{repo_path}/tar.gz/{ref}'
        print(f'== {name}: downloading {dl_url}', flush=True)
        try:
            download(dl_url, tgz)
        except Exception as e:
            print(f'!! {name}: download failed: {e}', file=sys.stderr)
            sys.exit(1)
        os.makedirs(target, exist_ok=True)
        extract(tgz, target)
    print('All tarballs downloaded and extracted')

def dev_all():
    # lime tooling resolves deps via the GLOBAL repo (~/.haxelib) even when
    # we run 'haxelib --never run lime'. hmm install populates the LOCAL repo
    # (.haxelib) with official lime 8.3.2 + hxcpp. So dev-link EVERY git dep
    # into BOTH repos: global (so lime internals find fork hxcpp/lime) and
    # local (so hmm-managed libs get overridden by forks).
    for flags in (['--global'], ['--never']):
        # repo may not exist yet; creation error is fine if it does exist
        try:
            subprocess.run(['haxelib'] + flags + ['newrepo', '--quiet'], check=True,
                           capture_output=True)
        except subprocess.CalledProcessError:
            pass
        try:
            subprocess.run(['haxelib'] + flags + ['fixrepo'], check=True,
                           capture_output=True)
        except subprocess.CalledProcessError:
            pass
    for dep in git_deps:
        name = dep['name']
        if name == 'hxcpp':
            # hmm installs a PRE-COMPILED hxcpp into the LOCAL repo (.haxelib).
            # lime tooling, however, resolves hxcpp via the GLOBAL repo when it
            # builds (we saw 'Library hxcpp is not installed'). Dev-linking the
            # fork (source) to global gives 'Can't continue without hxcpp.n'
            # because the source isn't built. So: install the OFFICIAL precompiled
            # hxcpp into the GLOBAL repo too, and do NOT dev-link the fork.
            print(f'== {name}: installing precompiled to global repo', flush=True)
            try:
                subprocess.run(['haxelib', '--global', 'install', 'hxcpp'],
                               check=True, capture_output=True)
                print(f'== {name}: global install OK', flush=True)
            except subprocess.CalledProcessError as e:
                print(f'!! {name}: global install failed rc={e.returncode}, '
                      f'continuing (may already exist)', flush=True)
            continue
        target = os.path.join(BASE, name)
        dev_path = target
        if dep.get('dir'):
            dev_path = os.path.join(target, dep['dir'])
        for flags in (['--global'], ['--never']):
            print(f'== {name}: haxelib {" ".join(flags)} dev -> {dev_path}', flush=True)
            subprocess.run(['haxelib'] + flags + ['dev', name, dev_path], check=True)
    print('All git deps dev-linked (global + local repo)')

if MODE == 'prepare':
    # Persist git deps for the later dev() call (hmm.json gets stripped below)
    with open(DEPS_CACHE, 'w') as f:
        json.dump(git_deps, f, indent=2)
    print(f'Cached {len(git_deps)} git deps to {DEPS_CACHE}')
    # Strip git deps so `hmm install` only handles haxelib deps,
    # then download + extract tarballs (no dev links yet)
    data['dependencies'] = [d for d in deps if d.get('type') != 'git']
    with open('hmm.json', 'w') as f:
        json.dump(data, f, indent=2)
    print(f'Removed {len(git_deps)} git deps from hmm.json, kept {len(data["dependencies"])} haxelib deps')
    fetch_all()
elif MODE == 'dev':
    # hmm.json was stripped by prepare(), reload git deps from cache.
    # (module-level name, no 'global' statement allowed at top level)
    git_deps = load_git_deps()
    print(f'Loaded {len(git_deps)} git deps from cache/hmm.json')
    if not git_deps:
        print('!! No git deps found - dev links will be empty!', file=sys.stderr)
        sys.exit(1)
    # Cache may have hit (tarballs in /tmp wiped), so fetch first (skips existing)
    fetch_all()
    dev_all()
else:
    # all: prepare + dev (legacy / local runs)
    with open(DEPS_CACHE, 'w') as f:
        json.dump(git_deps, f, indent=2)
    data['dependencies'] = [d for d in deps if d.get('type') != 'git']
    with open('hmm.json', 'w') as f:
        json.dump(data, f, indent=2)
    print(f'Removed {len(git_deps)} git deps from hmm.json, kept {len(data["dependencies"])} haxelib deps')
    fetch_all()
    dev_all()
