#!/usr/bin/env python3
"""
Detect which JDK (8, 11 or 17) a Maven project should be built and tested with.

Usage:  python detect_java_version.py <module_path>
Run from the root of the checked-out target repository.

It reads the module's pom.xml (and any parent POMs reachable on disk), collects
every Java level the project declares, takes the HIGHEST one, and rounds it up
to the nearest supported LTS:

    declared <= 8   -> 8   (also the default when nothing is declared)
    declared 9-11   -> 11
    declared 12-17  -> 17
    declared > 17   -> 17  (best effort; compilation will probably fail)

Signals read:
  * properties: maven.compiler.{release,source,target,testRelease,testSource,
    testTarget}, java.version, jdk.version, java.source.version, ...
  * maven-compiler-plugin <release>/<source>/<target> (incl. pluginManagement)
  * maven-enforcer-plugin <requireJavaVersion> (lower bound)
  * Spring Boot parent 3.x (requires 17)

Environment:
  FORCE_JAVA_VERSION   if set to 8/11/17, skips detection entirely
  GITHUB_OUTPUT        if set, writes java_version / declared_version / reason
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

SUPPORTED = (8, 11, 17)

PROPERTY_KEYS = (
    "maven.compiler.release", "maven.compiler.source", "maven.compiler.target",
    "maven.compiler.testRelease", "maven.compiler.testSource", "maven.compiler.testTarget",
    "java.version", "jdk.version", "java.source.version", "java.target.version",
    "javaVersion", "jdkVersion", "jdk.release", "compiler.version", "compiler.source",
    "compiler.target", "source.version", "target.version",
)
COMPILER_TAGS = ("release", "source", "target", "testRelease", "testSource", "testTarget")


def load_pom(path):
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    for el in root.iter():  # drop XML namespaces so find('parent') etc. work
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def text_of(el, name):
    child = el.find(name)
    return child.text.strip() if child is not None and child.text else None


def pom_chain(repo_root, module_path):
    """Module pom, then each local parent pom, then the repo root pom (if not already seen)."""
    repo_root = os.path.realpath(repo_root)
    start = os.path.realpath(os.path.join(repo_root, module_path, "pom.xml"))
    chain, seen, cur = [], set(), start
    while cur and cur not in seen and os.path.isfile(cur) and cur.startswith(repo_root):
        seen.add(cur)
        root = load_pom(cur)
        if root is None:
            break
        chain.append((cur, root))
        parent = root.find("parent")
        if parent is None:
            break
        rel = text_of(parent, "relativePath")
        if rel is None:
            rel = "../pom.xml"  # Maven default
        if rel == "":
            break  # explicitly "do not look locally"
        nxt = os.path.realpath(os.path.join(os.path.dirname(cur), rel))
        cur = os.path.join(nxt, "pom.xml") if os.path.isdir(nxt) else nxt
    root_pom = os.path.join(repo_root, "pom.xml")
    if os.path.isfile(root_pom) and root_pom not in seen:
        root = load_pom(root_pom)
        if root is not None:
            chain.append((root_pom, root))
    return chain


def merged_properties(chain):
    props = {}
    for _, root in reversed(chain):  # parents first, children override
        # 1. Base properties
        block = root.find("properties")
        if block is not None:
            for p in block:
                if isinstance(p.tag, str) and p.text:
                    props[p.tag] = p.text.strip()
        
        # 2. Profile properties (optimistically include them)
        for profile in root.iter("profile"):
            p_block = profile.find("properties")
            if p_block is not None:
                for p in p_block:
                    if isinstance(p.tag, str) and p.text:
                        props[p.tag] = p.text.strip()
    return props


def resolve(value, props):
    for _ in range(5):
        new = re.sub(r"\$\{([^}]+)\}", lambda m: props.get(m.group(1), m.group(0)), value)
        if new == value:
            break
        value = new
    return value


def normalize(value):
    """'1.8' -> 8, '11' -> 11, '17.0.1' -> 17. Returns None if not a Java level."""
    m = re.match(r"^(?:1\.)?(\d{1,2})(?:\.\d+)*$", value.strip())
    if not m:
        return None
    v = int(m.group(1))
    return v if 5 <= v <= 40 else None


def enforcer_lower_bound(expr):
    expr = expr.strip().lstrip("[(").rstrip("])")
    lower = expr.split(",")[0].strip()
    return normalize(lower) if lower else None


def find_declared(chain, props):
    found = []  # (version, where)

    for key in PROPERTY_KEYS:
        if key in props:
            v = normalize(resolve(props[key], props))
            if v:
                found.append((v, "property " + key))

    for path, root in chain:
        rel = os.path.relpath(path)
        for profile in root.findall(".//profile"):
            act = profile.find("activation")
            if act is not None:
                jdk = text_of(act, "jdk")
                # Ignore negative activations like "!1.8"
                if jdk and not jdk.startswith("!"):
                    v = enforcer_lower_bound(resolve(jdk, props))
                    if v:
                        found.append((v, "profile activation jdk " + jdk + " in " + rel))
        for plugin in root.findall(".//plugin"):
            artifact = text_of(plugin, "artifactId")
            if artifact == "maven-compiler-plugin":
                for tag in COMPILER_TAGS:
                    for el in plugin.iter(tag):
                        if el.text:
                            v = normalize(resolve(el.text, props))
                            if v:
                                found.append((v, "compiler <%s> in %s" % (tag, rel)))
            elif artifact == "maven-enforcer-plugin":
                for el in plugin.iter("requireJavaVersion"):
                    ver = text_of(el, "version")
                    if ver:
                        v = enforcer_lower_bound(resolve(ver, props))
                        if v:
                            found.append((v, "enforcer requireJavaVersion in " + rel))

        parent = root.find("parent")
        if parent is not None and text_of(parent, "groupId") == "org.springframework.boot":
            ver = text_of(parent, "version") or ""
            if ver.startswith("3."):
                found.append((17, "Spring Boot parent " + ver))

    return found


def pick_supported(declared):
    for s in SUPPORTED:
        if declared <= s:
            return s
    return SUPPORTED[-1]


def main():
    module_path = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "."

    forced = os.environ.get("FORCE_JAVA_VERSION", "").strip()
    if forced:
        if forced not in {str(s) for s in SUPPORTED}:
            sys.exit("FORCE_JAVA_VERSION must be one of %s, got %r" % (SUPPORTED, forced))
        declared, chosen, reason = int(forced), int(forced), "forced via workflow input"
    else:
        chain = pom_chain(".", module_path)
        found = find_declared(chain, merged_properties(chain)) if chain else []
        if not found:
            declared, chosen = 8, 8
            reason = "no Java level declared (or no pom.xml found); defaulting to 8"
        else:
            declared, where = max(found, key=lambda f: f[0])
            chosen = pick_supported(declared)
            reason = "declared Java %d (%s) -> using JDK %d" % (declared, where, chosen)
            if declared > SUPPORTED[-1]:
                reason += " [WARNING: newer than the highest supported JDK; build will likely fail]"

    print("::notice title=Java version::%s" % reason)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write("java_version=%d\n" % chosen)
            fh.write("declared_version=%d\n" % declared)
            fh.write("reason=%s\n" % reason.replace("\n", " "))
    else:
        print("java_version=%d" % chosen)


if __name__ == "__main__":
    main()
