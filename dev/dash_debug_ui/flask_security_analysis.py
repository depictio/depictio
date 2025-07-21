#!/usr/bin/env python3
"""
Enterprise Flask/Dash Security Assessment Scanner
Comprehensive security assessment for Flask/Dash applications
"""

import concurrent.futures
import json
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests


@dataclass
class SecurityFinding:
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    category: str
    title: str
    description: str
    evidence: List[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class ServerAssessment:
    url: str
    server_type: str = "Unknown"
    is_reachable: bool = False
    response_time: float = 0.0
    server_header: str = ""
    findings: List[SecurityFinding] = field(default_factory=list)
    dash_config: Dict = field(default_factory=dict)
    risk_score: int = 0

    def add_finding(self, finding: SecurityFinding):
        self.findings.append(finding)
        # Update risk score
        score_map = {"CRITICAL": 100, "HIGH": 75, "MEDIUM": 50, "LOW": 25, "INFO": 5}
        self.risk_score += score_map.get(finding.severity, 0)


class FlaskSecurityScanner:
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SecurityScanner/1.0"})

    def scan_server(self, url: str) -> ServerAssessment:
        """Perform comprehensive security assessment of a server"""
        assessment = ServerAssessment(url=url)

        print(f"\n🔍 Scanning {url}")
        print("=" * 60)

        # Basic connectivity test
        if not self._test_connectivity(assessment):
            return assessment

        # Perform all security checks
        self._check_server_headers(assessment)
        self._check_debug_mode(assessment)
        self._check_debug_endpoints(assessment)
        self._check_dash_configuration(assessment)
        self._check_error_handling(assessment)
        self._check_security_headers(assessment)
        self._check_information_disclosure(assessment)
        self._analyze_application_type(assessment)

        return assessment

    def _test_connectivity(self, assessment: ServerAssessment) -> bool:
        """Test basic connectivity and response time"""
        try:
            start_time = time.time()
            response = self.session.get(assessment.url, timeout=self.timeout)
            assessment.response_time = time.time() - start_time
            assessment.is_reachable = True

            print(f"✅ Server reachable (Response time: {assessment.response_time:.2f}s)")
            return True

        except requests.exceptions.RequestException as e:
            assessment.add_finding(
                SecurityFinding(
                    severity="HIGH",
                    category="Connectivity",
                    title="Server Unreachable",
                    description=f"Cannot connect to server: {str(e)}",
                    recommendation="Verify server is running and accessible",
                )
            )
            print(f"❌ Server unreachable: {e}")
            return False

    def _check_server_headers(self, assessment: ServerAssessment):
        """Analyze server headers for development indicators"""
        try:
            response = self.session.get(assessment.url, timeout=self.timeout)
            assessment.server_header = response.headers.get("Server", "")

            server_lower = assessment.server_header.lower()

            # Check for development server indicators
            if "werkzeug" in server_lower:
                assessment.server_type = "Flask Development Server"
                assessment.add_finding(
                    SecurityFinding(
                        severity="CRITICAL",
                        category="Server Configuration",
                        title="Flask Development Server Detected",
                        description="Werkzeug development server detected in production",
                        evidence=[f"Server header: {assessment.server_header}"],
                        recommendation="Use production WSGI server (gunicorn, uwsgi, etc.)",
                    )
                )
            elif "gunicorn" in server_lower:
                assessment.server_type = "Gunicorn (Production)"
                assessment.add_finding(
                    SecurityFinding(
                        severity="INFO",
                        category="Server Configuration",
                        title="Production Server Detected",
                        description="Running on production WSGI server",
                        evidence=[f"Server header: {assessment.server_header}"],
                    )
                )
            elif "python" in server_lower and "flask" in server_lower:
                assessment.server_type = "Flask (Unknown Configuration)"
                assessment.add_finding(
                    SecurityFinding(
                        severity="MEDIUM",
                        category="Server Configuration",
                        title="Flask Server with Python Reference",
                        description="Server header indicates Flask with Python version",
                        evidence=[f"Server header: {assessment.server_header}"],
                        recommendation="Review server configuration for production readiness",
                    )
                )

            print(f"🖥️  Server Type: {assessment.server_type}")
            print(f"📋 Server Header: {assessment.server_header}")

        except Exception as e:
            assessment.add_finding(
                SecurityFinding(
                    severity="LOW",
                    category="Analysis",
                    title="Header Analysis Failed",
                    description=f"Could not analyze server headers: {str(e)}",
                )
            )

    def _check_debug_mode(self, assessment: ServerAssessment):
        """Check for Flask debug mode by analyzing error responses"""
        debug_test_paths = [
            "/nonexistent-endpoint-12345",
            "/debug-test-path",
            "/trigger-error-test",
            "/%2e%2e/%2e%2e/etc/passwd",  # Path traversal attempt
        ]

        debug_indicators = [
            "traceback (most recent call last)",
            "werkzeug debugger",
            'file "/',
            "line ",
            "in <module>",
            "builtins.",
            "site-packages/",
            "interactive debugger",
            "pin-based authentication",
            "debugger pin",
            "console.html",
        ]

        for test_path in debug_test_paths:
            try:
                response = self.session.get(f"{assessment.url}{test_path}", timeout=self.timeout)
                content = response.text.lower()

                found_indicators = [
                    indicator for indicator in debug_indicators if indicator in content
                ]

                if found_indicators:
                    assessment.add_finding(
                        SecurityFinding(
                            severity="CRITICAL",
                            category="Debug Mode",
                            title="Flask Debug Mode Enabled",
                            description="Flask application is running in debug mode, exposing sensitive information",
                            evidence=found_indicators[:3],  # Limit evidence for readability
                            recommendation="Set debug=False and use production error handling",
                        )
                    )
                    print(f"🚨 Debug mode detected via {test_path}")
                    return  # No need to test further

            except Exception:
                continue

        print(f"✅ No debug mode indicators found")

    def _check_debug_endpoints(self, assessment: ServerAssessment):
        """Check for accessible debug endpoints"""
        debug_endpoints = [
            "/console",
            "/__debugger__",
            "/debugger",
            "/debug",
            "/_debug_toolbar",
            "/werkzeug",
            "/debug-console",
        ]

        accessible_endpoints = []

        for endpoint in debug_endpoints:
            try:
                response = self.session.get(f"{assessment.url}{endpoint}", timeout=self.timeout)
                if response.status_code not in [404, 403, 500]:
                    accessible_endpoints.append(f"{endpoint} (HTTP {response.status_code})")

            except Exception:
                continue

        if accessible_endpoints:
            assessment.add_finding(
                SecurityFinding(
                    severity="CRITICAL",
                    category="Debug Endpoints",
                    title="Debug Endpoints Accessible",
                    description="Debug/console endpoints are accessible",
                    evidence=accessible_endpoints,
                    recommendation="Block debug endpoints in production",
                )
            )
            print(f"🚨 Accessible debug endpoints: {', '.join(accessible_endpoints)}")
        else:
            print(f"✅ No accessible debug endpoints")

    def _check_dash_configuration(self, assessment: ServerAssessment):
        """Analyze Dash-specific configuration"""
        try:
            response = self.session.get(assessment.url, timeout=self.timeout)

            # Extract _dash-config JSON
            config_match = re.search(
                r'<script id="_dash-config" type="application/json">(.*?)</script>',
                response.text,
                re.DOTALL,
            )

            if config_match:
                try:
                    assessment.dash_config = json.loads(config_match.group(1))

                    # Check hot reload configuration
                    hot_reload = assessment.dash_config.get("hot_reload", {})
                    if hot_reload and hot_reload.get("interval"):
                        assessment.add_finding(
                            SecurityFinding(
                                severity="MEDIUM",
                                category="Dash Configuration",
                                title="Hot Reload Configured",
                                description="Dash hot reload is configured (may not work with production servers)",
                                evidence=[f"Hot reload interval: {hot_reload.get('interval')}ms"],
                                recommendation="Disable hot reload in production",
                            )
                        )

                    # Check props checking
                    if assessment.dash_config.get("props_check") is True:
                        assessment.add_finding(
                            SecurityFinding(
                                severity="LOW",
                                category="Dash Configuration",
                                title="Props Checking Enabled",
                                description="Dash props checking is enabled (development feature)",
                                evidence=["props_check: true"],
                                recommendation="Consider disabling props checking in production for performance",
                            )
                        )

                    # Check UI debug tools
                    if assessment.dash_config.get("ui") is True:
                        assessment.add_finding(
                            SecurityFinding(
                                severity="INFO",
                                category="Dash Configuration",
                                title="Dash Debug UI Enabled",
                                description="Dash debug UI tools are enabled",
                                evidence=["ui: true"],
                                recommendation="Debug UI can be useful for troubleshooting but consider security implications",
                            )
                        )

                    print(f"📊 Dash application detected")

                except json.JSONDecodeError:
                    assessment.add_finding(
                        SecurityFinding(
                            severity="LOW",
                            category="Analysis",
                            title="Dash Config Parse Error",
                            description="Found Dash config but could not parse JSON",
                        )
                    )

        except Exception as e:
            pass  # Not a Dash app or other error

    def _check_error_handling(self, assessment: ServerAssessment):
        """Test error handling behavior"""
        error_test_urls = [
            f"{assessment.url}/this-definitely-does-not-exist-12345",
            f"{assessment.url}/admin/secret/path",
        ]

        for test_url in error_test_urls:
            try:
                response = self.session.get(test_url, timeout=self.timeout)

                # Check if detailed error information is exposed
                if response.status_code == 500:
                    if "traceback" in response.text.lower() or "exception" in response.text.lower():
                        assessment.add_finding(
                            SecurityFinding(
                                severity="HIGH",
                                category="Error Handling",
                                title="Detailed Error Information Exposed",
                                description="Server returns detailed error information on 500 errors",
                                evidence=[f"HTTP 500 with detailed error info"],
                                recommendation="Implement proper error handling and logging",
                            )
                        )
                        break

            except Exception:
                continue

    def _check_security_headers(self, assessment: ServerAssessment):
        """Check for security headers"""
        try:
            response = self.session.get(assessment.url, timeout=self.timeout)

            security_headers = {
                "X-Frame-Options": "Clickjacking protection",
                "X-Content-Type-Options": "MIME type sniffing protection",
                "X-XSS-Protection": "XSS protection",
                "Strict-Transport-Security": "HTTPS enforcement",
                "Content-Security-Policy": "Content security policy",
                "Referrer-Policy": "Referrer policy",
            }

            missing_headers = []
            for header, description in security_headers.items():
                if header not in response.headers:
                    missing_headers.append(f"{header} ({description})")

            if missing_headers:
                assessment.add_finding(
                    SecurityFinding(
                        severity="MEDIUM",
                        category="Security Headers",
                        title="Missing Security Headers",
                        description="Important security headers are missing",
                        evidence=missing_headers[:3],  # Limit for readability
                        recommendation="Implement security headers for production deployment",
                    )
                )
                print(f"⚠️  Missing {len(missing_headers)} security headers")
            else:
                print(f"✅ Security headers present")

        except Exception:
            pass

    def _check_information_disclosure(self, assessment: ServerAssessment):
        """Check for information disclosure"""
        try:
            response = self.session.get(assessment.url, timeout=self.timeout)

            # Check for development asset bundles
            dev_js_count = len(re.findall(r"\.dev\.js", response.text))
            if dev_js_count > 0:
                assessment.add_finding(
                    SecurityFinding(
                        severity="LOW",
                        category="Information Disclosure",
                        title="Development Asset Bundles",
                        description="Application is serving development JavaScript bundles",
                        evidence=[f"{dev_js_count} .dev.js files found"],
                        recommendation="Use production asset bundles",
                    )
                )

            # Check for version information
            version_patterns = [
                r'version["\s]*[:=]["\s]*([0-9.]+)',
                r"v([0-9]+\.[0-9]+\.[0-9]+)",
                r"dash.*?v([0-9]+\.[0-9]+\.[0-9]+)",
            ]

            for pattern in version_patterns:
                matches = re.findall(pattern, response.text, re.IGNORECASE)
                if matches:
                    assessment.add_finding(
                        SecurityFinding(
                            severity="INFO",
                            category="Information Disclosure",
                            title="Version Information Disclosed",
                            description="Application version information is exposed",
                            evidence=[f"Version: {match}" for match in matches[:2]],
                            recommendation="Consider removing version information from public responses",
                        )
                    )
                    break

        except Exception:
            pass

    def _analyze_application_type(self, assessment: ServerAssessment):
        """Determine application type and framework"""
        try:
            response = self.session.get(assessment.url, timeout=self.timeout)
            content = response.text.lower()

            # Framework detection
            if "dash" in content and "_dash-config" in content:
                assessment.add_finding(
                    SecurityFinding(
                        severity="INFO",
                        category="Application Analysis",
                        title="Dash Application Detected",
                        description="Application appears to be built with Plotly Dash framework",
                    )
                )
            elif "flask" in content:
                assessment.add_finding(
                    SecurityFinding(
                        severity="INFO",
                        category="Application Analysis",
                        title="Flask Application Detected",
                        description="Application appears to be built with Flask framework",
                    )
                )

        except Exception:
            pass

    def print_assessment_report(self, assessment: ServerAssessment):
        """Print detailed assessment report"""
        print(f"\n" + "=" * 80)
        print(f"SECURITY ASSESSMENT REPORT: {assessment.url}")
        print(f"=" * 80)

        # Basic information
        print(f"\n📋 BASIC INFORMATION")
        print(f"├── Server Type: {assessment.server_type}")
        print(f"├── Reachable: {'✅ Yes' if assessment.is_reachable else '❌ No'}")
        print(f"├── Response Time: {assessment.response_time:.2f}s")
        print(f"├── Server Header: {assessment.server_header}")
        print(f"└── Risk Score: {assessment.risk_score}")

        # Risk level assessment
        if assessment.risk_score >= 200:
            risk_level = "🔴 CRITICAL"
        elif assessment.risk_score >= 100:
            risk_level = "🟠 HIGH"
        elif assessment.risk_score >= 50:
            risk_level = "🟡 MEDIUM"
        else:
            risk_level = "🟢 LOW"

        print(f"\n🎯 OVERALL RISK LEVEL: {risk_level}")

        # Findings by severity
        findings_by_severity = {}
        for finding in assessment.findings:
            if finding.severity not in findings_by_severity:
                findings_by_severity[finding.severity] = []
            findings_by_severity[finding.severity].append(finding)

        severity_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        severity_icons = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "ℹ️"}

        for severity in severity_order:
            if severity in findings_by_severity:
                print(
                    f"\n{severity_icons[severity]} {severity} FINDINGS ({len(findings_by_severity[severity])})"
                )

                for i, finding in enumerate(findings_by_severity[severity]):
                    prefix = "├──" if i < len(findings_by_severity[severity]) - 1 else "└──"
                    print(f"{prefix} {finding.title}")
                    print(f"    Description: {finding.description}")

                    if finding.evidence:
                        print(f"    Evidence: {', '.join(finding.evidence[:2])}")

                    if finding.recommendation:
                        print(f"    Recommendation: {finding.recommendation}")
                    print()

    def scan_multiple_servers(self, urls: List[str]) -> List[ServerAssessment]:
        """Scan multiple servers and return assessments"""
        assessments = []

        print(f"🔍 FLASK/DASH SECURITY ASSESSMENT")
        print(f"Scanning {len(urls)} servers...")

        for url in urls:
            assessment = self.scan_server(url)
            assessments.append(assessment)
            self.print_assessment_report(assessment)

        # Summary report
        self._print_summary_report(assessments)

        return assessments

    def _print_summary_report(self, assessments: List[ServerAssessment]):
        """Print summary report for all assessments"""
        print(f"\n" + "=" * 80)
        print(f"SUMMARY REPORT")
        print(f"=" * 80)

        total_critical = sum(
            len([f for f in a.findings if f.severity == "CRITICAL"]) for a in assessments
        )
        total_high = sum(len([f for f in a.findings if f.severity == "HIGH"]) for a in assessments)
        total_medium = sum(
            len([f for f in a.findings if f.severity == "MEDIUM"]) for a in assessments
        )

        print(f"\n📊 FINDINGS SUMMARY")
        print(f"├── 🚨 Critical: {total_critical}")
        print(f"├── ⚠️  High: {total_high}")
        print(f"├── 🟡 Medium: {total_medium}")
        print(f"└── 📋 Total Servers: {len(assessments)}")

        print(f"\n🎯 RISK ASSESSMENT")
        for assessment in assessments:
            if assessment.risk_score >= 200:
                risk_icon = "🔴"
            elif assessment.risk_score >= 100:
                risk_icon = "🟠"
            elif assessment.risk_score >= 50:
                risk_icon = "🟡"
            else:
                risk_icon = "🟢"

            print(f"{risk_icon} {assessment.url} (Score: {assessment.risk_score})")

        # Recommendations
        print(f"\n💡 TOP RECOMMENDATIONS")
        critical_findings = [f for a in assessments for f in a.findings if f.severity == "CRITICAL"]
        recommendations = set()
        for finding in critical_findings[:3]:  # Top 3 critical
            if finding.recommendation:
                recommendations.add(finding.recommendation)

        for i, rec in enumerate(list(recommendations)[:3], 1):
            print(f"{i}. {rec}")


def main():
    """Main function to run the security assessment"""
    # Target servers
    servers = ["http://0.0.0.0:5080", "http://0.0.0.0:8050"]

    scanner = FlaskSecurityScanner(timeout=10)
    assessments = scanner.scan_multiple_servers(servers)

    print(f"\n✅ Assessment completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
