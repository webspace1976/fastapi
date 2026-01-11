# utils/renderer.py
def render_check_result(results: list) -> str:
    html = ["<pre>"]
    for r in results:
        if "error" in r:
            html.append(f"<h3 style='color:red'>FAILED {r['ip']}</h3><p>{r['error']}</p><hr>")
        else:
            html.append(f"<h3 style='color:green'>SUCCESS: {r['hostname']} ({r['ip']})</h3>")
            html.append(f"BGP: <strong>{r['bgp_up']}/{r['bgp_total']}</strong> | OSPF: <strong>{r['ospf_full']}/{r['ospf_total']}</strong><hr>")
    html.append("</pre>")
    return "".join(html)