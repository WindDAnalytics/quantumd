import json
from pathlib import Path

def render_html_report(project_dir: Path) -> Path:
    latest_pointer = project_dir / "evidence" / "latest.json"
    if not latest_pointer.exists():
        raise FileNotFoundError(f"No evidence pointer found in {project_dir}")
        
    pointer = json.loads(latest_pointer.read_text(encoding="utf-8"))
    record_path = project_dir / pointer["record"]
    data = json.loads(record_path.read_text(encoding="utf-8"))
    
    integrity = data.get("integrity", {})
    gates = data.get("gates", [])
    
    # Check signature status
    is_signed = integrity.get("signed", False)
    pub_verified = pointer.get("public_key_signature_verified", integrity.get("public_key_signature_verified", False))
    
    if pub_verified:
        sig_status = "CRYPTOGRAPHICALLY ATTESTED (PUBLIC KEY VERIFIED)"
        sig_color = "#10b981"
    elif is_signed:
        sig_status = "SIGNED BY PROVIDER (UNVERIFIED PUBLIC KEY)"
        sig_color = "#f59e0b"
    else:
        sig_status = "TAMPER-EVIDENT ONLY (UNSIGNED)"
        sig_color = "#ef4444"
        
    final_decision = data.get('final_decision', 'UNKNOWN')
    decision_color = "#10b981" if "VERIFIED" in final_decision and "DENIED" not in final_decision else "#ef4444"
    if "EDUCATIONAL" in final_decision: decision_color = "#f59e0b"

    project_name = data.get("project", dict()).get("name", "Unknown")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>QuantumD Evidence: {data.get('run_id')}</title>
    <style>
        body {{ font-family: -apple-system, system-ui, sans-serif; background: #f9fafb; color: #111827; padding: 40px; line-height: 1.5; }}
        .container {{ max-width: 900px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-top: 6px solid #4f46e5; }}
        .header {{ border-bottom: 2px solid #e5e7eb; padding-bottom: 20px; margin-bottom: 30px; }}
        .status-box {{ padding: 15px; border-radius: 6px; font-weight: bold; text-align: center; margin-bottom: 20px; background-color: {decision_color}20; border: 1px solid {decision_color}; color: {decision_color}; font-size: 1.25rem; }}
        .sig-box {{ background: {sig_color}10; border-left: 4px solid {sig_color}; padding: 15px; border-radius: 4px; font-size: 14px; font-family: monospace; overflow-x: auto; word-break: break-all; margin-bottom: 30px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
        th {{ background: #f3f4f6; }}
        .pass {{ color: #10b981; font-weight: bold; }}
        .fail {{ color: #ef4444; font-weight: bold; }}
        .skipped {{ color: #6b7280; font-style: italic; }}
        pre {{ background: #f3f4f6; padding: 10px; border-radius: 4px; font-size: 12px; margin: 0; overflow-x: auto; color: #374151; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>QuantumD Evidence Attestation</h2>
            <p><strong>Run ID:</strong> {data.get('run_id')}</p>
            <p><strong>Project:</strong> {project_name}</p>
            <p><strong>Timestamp:</strong> {data.get('finalized_at')}</p>
        </div>
        
        <div class="status-box">
            FINAL VERDICT: {final_decision}
        </div>
        
        <div class="sig-box">
            <strong style="color: {sig_color}; font-size: 1.1em;">Security Level: {sig_status}</strong><br><br>
            <strong>Payload Hash:</strong><br>{integrity.get('canonical_payload_sha256', 'N/A')}<br><br>
            <strong>Signer Key:</strong><br>{integrity.get('key_version', 'None')}
        </div>
        
        <h3>Verification Gates</h3>
        <table>
            <tr><th style="width: 20%">Gate</th><th style="width: 15%">Status</th><th>Details</th></tr>
"""
    for g in gates:
        status = g.get('status', 'UNKNOWN')
        cls = "pass" if status == "PASS" else ("fail" if status in ["FAIL", "ERROR"] else "skipped")
        details = g.get('details', '')
        
        if isinstance(details, dict):
            if 'message' in details:
                details = details['message']
            elif 'decision' in details:
                method = details.get('comparison', {}).get('method', 'unknown')
                details = f"<strong>{details['decision']}</strong> (Method: {method})"
            else:
                details = f"<pre>{json.dumps(details, indent=2)}</pre>"
                
        html += f"<tr><td>{g.get('gate').replace('_', ' ').title()}</td><td class='{cls}'>{status}</td><td>{details}</td></tr>\n"
        
    html += """
        </table>
        <p style="text-align: center; margin-top: 40px; font-size: 0.85em; color: #6b7280;">
            <em>QuantumD exists to produce trustworthy evidence, not favorable quantum results.</em>
        </p>
    </div>
</body>
</html>
"""
    reports_dir = project_dir / "evidence" / "reports"
    reports_dir.mkdir(exist_ok=True)
    out_file = reports_dir / f"report.html"
    out_file.write_text(html, encoding="utf-8")
    return out_file
