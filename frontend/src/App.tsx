/**
 * Routes, guards and the two navigations.
 *
 * The paths below are not all chosen here. The backend writes frontend routes into its own
 * responses - `link` on a notification, `link` on a report row, `url` on a source - and those
 * strings are `/response-center/reports/{id}`, `/response-center/requests/{ref_code}`,
 * `/requests/{ref_code}` and `/community/report`. This file has to match them character for
 * character or a link the platform sent its own user becomes a 404 in the platform. That
 * coupling is uncomfortable (it is in docs/known-issues.md) and the alternative - rewriting
 * links on the way through the UI - would break every one the user copies out of an SMS.
 *
 * Guards decide which product you are looking at, from the account, never from the address
 * bar: a resident who types `/response-center/queue` is sent to their own home rather than
 * shown a queue that would answer 403 a second later.
 */

import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { homeFor, useAuth } from "./auth/AuthContext";
import { AppShell } from "./components/AppShell";
import type { NavItem } from "./components/AppShell";
import { Loading } from "./components/StatePanel";
import { LoginPage } from "./pages/LoginPage";
import { NotBuilt } from "./pages/NotBuilt";
import { AccountPage } from "./pages/community/AccountPage";
import { AskPage } from "./pages/community/AskPage";
import { HelpPage } from "./pages/community/HelpPage";
import { HomePage } from "./pages/community/HomePage";
import { IncidentPage } from "./pages/community/IncidentPage";
import { MinePage } from "./pages/community/MinePage";
import { MyRequestPage } from "./pages/community/MyRequestPage";
import { ReportPage } from "./pages/community/ReportPage";
import { ActivityPage } from "./pages/rc/ActivityPage";
import { AssistantPage } from "./pages/rc/AssistantPage";
import { AuditPage } from "./pages/rc/AuditPage";
import { IncidentDetailPage } from "./pages/rc/IncidentDetailPage";
import { IncidentsPage } from "./pages/rc/IncidentsPage";
import { OverviewPage } from "./pages/rc/OverviewPage";
import { QueuePage } from "./pages/rc/QueuePage";
import { ReportDetailPage } from "./pages/rc/ReportDetailPage";
import { ReportsPage } from "./pages/rc/ReportsPage";
import { RequestDetailPage } from "./pages/rc/RequestDetailPage";
import { RequestsPage } from "./pages/rc/RequestsPage";
import { ResourcesPage } from "./pages/rc/ResourcesPage";
import { SourcesPage } from "./pages/rc/SourcesPage";

/* ------------------------------------------------------------------ navigation */

const RC_NAV: NavItem[] = [
  { to: "/response-center", label: "nav_overview", permission: "incidents:read", exact: true },
  { to: "/response-center/queue", label: "nav_queue", permission: "assistance:read" },
  { to: "/response-center/incidents", label: "nav_incidents", permission: "incidents:read" },
  { to: "/response-center/reports", label: "nav_reports", permission: "reports:read" },
  { to: "/response-center/requests", label: "nav_requests", permission: "assistance:read" },
  { to: "/response-center/resources", label: "nav_resources", permission: "resources:read" },
  { to: "/response-center/sources", label: "nav_sources", permission: "sources:read" },
  { to: "/response-center/activity", label: "nav_activity", permission: "incidents:read" },
  { to: "/response-center/audit", label: "nav_audit", permission: "audit:read" },
  { to: "/response-center/assistant", label: "nav_assistant", permission: "agent:run" },
];

const CM_NAV: NavItem[] = [
  { to: "/community", label: "nav_feed", exact: true },
  { to: "/community/report", label: "nav_report", permission: "community:report" },
  { to: "/community/help", label: "nav_help", permission: "community:request" },
  { to: "/community/mine", label: "nav_mine", permission: "community:read_own" },
  { to: "/community/account", label: "nav_account" },
];

/* ------------------------------------------------------------------ guards */

function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "booting") return <Loading />;
  if (status !== "signed_in") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

function RequireSurface({ surface }: { surface: "response_center" | "community" }) {
  const { surface: mine } = useAuth();
  if (mine && mine !== surface) return <Navigate to={homeFor(mine)} replace />;
  return <Outlet />;
}

function LoginRoute() {
  const { status, surface } = useAuth();
  const location = useLocation();
  if (status === "signed_in") {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from ?? homeFor(surface)} replace />;
  }
  return <LoginPage />;
}

function HomeRedirect() {
  const { status, surface } = useAuth();
  if (status === "booting") return <Loading />;
  if (status !== "signed_in") return <Navigate to="/login" replace />;
  return <Navigate to={homeFor(surface)} replace />;
}

/**
 * The community notification link (`/requests/{ref_code}`) is surface-neutral, so a staff
 * member following one from their own notification list needs the console view of the same
 * request. One path in, one surface out - and both destinations are real routes, never this
 * one, or the redirect would land back on itself.
 */
function RequestLink() {
  const { isStaff } = useAuth();
  const { pathname } = useLocation();
  const refCode = pathname.split("/").filter(Boolean).pop() ?? "";
  const base = isStaff ? "/response-center" : "/community";
  return <Navigate to={`${base}/requests/${encodeURIComponent(refCode)}`} replace />;
}

/* ------------------------------------------------------------------ routes */

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginRoute />} />

        <Route element={<RequireAuth />}>
          <Route path="/" element={<HomeRedirect />} />
          <Route path="/requests/:refCode" element={<RequestLink />} />

          <Route element={<RequireSurface surface="response_center" />}>
            <Route path="/response-center" element={<AppShell items={RC_NAV} />}>
              <Route index element={<OverviewPage />} />
              <Route path="queue" element={<QueuePage />} />
              <Route path="incidents" element={<IncidentsPage />} />
              <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="reports/:reportId" element={<ReportDetailPage />} />
              <Route path="requests" element={<RequestsPage />} />
              <Route path="requests/:refCode" element={<RequestDetailPage />} />
              <Route path="resources" element={<ResourcesPage />} />
              <Route path="sources" element={<SourcesPage />} />
              <Route path="activity" element={<ActivityPage />} />
              <Route path="audit" element={<AuditPage />} />
              <Route path="assistant" element={<AssistantPage />} />
            </Route>
          </Route>

          <Route element={<RequireSurface surface="community" />}>
            <Route path="/community" element={<AppShell items={CM_NAV} />}>
              <Route index element={<HomePage />} />
              {/* Reachable from the feed; not a tab, because a resident
                  follows one situation at a time rather than browsing a register. */}
              <Route path="incidents/:incidentId" element={<IncidentPage />} />
              {/* Also not a tab. The home screen's first big button is the entry point, and a
                  question is something you have, not somewhere you go. */}
              <Route path="ask" element={<AskPage />} />
              <Route path="report" element={<ReportPage />} />
              <Route path="help" element={<HelpPage />} />
              <Route path="mine" element={<MinePage />} />
              <Route path="requests/:refCode" element={<MyRequestPage />} />
              <Route path="account" element={<AccountPage />} />
            </Route>
          </Route>
        </Route>

        <Route path="*" element={<NotBuilt />} />
      </Routes>
    </BrowserRouter>
  );
}
