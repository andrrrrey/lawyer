import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth } from "@/auth/RequireAuth";
import { RequireRole } from "@/auth/RequireRole";
import { AppLayout } from "@/layout/AppLayout";
import AiPage from "@/pages/AiPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import BusinessSettingsPage from "@/pages/BusinessSettingsPage";
import DashboardPage from "@/pages/DashboardPage";
import IntegrationsPage from "@/pages/IntegrationsPage";
import LoginPage from "@/pages/LoginPage";
import MonitorPage from "@/pages/MonitorPage";
import RomiPage from "@/pages/RomiPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/monitor" element={<MonitorPage />} />
          <Route path="/analytics" element={<RequireRole roles={["owner", "head"]}><AnalyticsPage /></RequireRole>} />
          <Route path="/romi" element={<RequireRole roles={["owner", "head"]}><RomiPage /></RequireRole>} />
          <Route path="/ai" element={<RequireRole roles={["owner", "head"]}><AiPage /></RequireRole>} />
          <Route path="/admin" element={<RequireRole roles={["owner"]}><Navigate to="/settings?tab=sla" replace /></RequireRole>} />
          <Route path="/settings" element={<RequireRole roles={["owner"]}><BusinessSettingsPage /></RequireRole>} />
          <Route path="/integrations" element={<RequireRole roles={["owner"]}><IntegrationsPage /></RequireRole>} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
