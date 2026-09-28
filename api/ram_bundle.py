"""Explicit RAM sales bundles: one ordered product can contain multiple DIMMs."""
import re


def ram_bundle(name: str):
    """Return a bundle only when the written total equals module size × count.

    Does not treat an ordinary 32GB DIMM as two modules, or manufacture a total
    from conflicting title numbers. BOM order quantity is applied by the caller.
    """
    name = name or ''
    layout = re.search(r'(\d+)\s*G(?:B)?\s*[x×]\s*(\d+)', name, re.I)
    if not layout:
        return None
    total = re.search(r'(\d+)\s*GB\b', name[:layout.start()], re.I)
    if not total:
        return None
    module, count = int(layout[1]), int(layout[2])
    if module <= 0 or count <= 0 or int(total[1]) != module * count:
        return None
    return {'total_gb': int(total[1]), 'module_gb': module, 'module_count': count}


def bundle_facts(name: str):
    bundle = ram_bundle(name)
    if not bundle:
        return []
    return [dict(label=k, value=v, source_id='merchant', verification='판매처 묶음 상품명 확인')
            for k, v in [('상품 용량', f"{bundle['total_gb']}GB"),
                         ('모듈당 용량', f"{bundle['module_gb']}GB"),
                         ('패키지 구성', f"{bundle['module_count']}개 (주문 1세트)")]]
