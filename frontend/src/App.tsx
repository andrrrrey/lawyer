import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth } from "@/auth/RequireAuth";
import { AppLayout } from "@/layout/AppLayout";
import AdminPage from "@/pages/AdminPage";
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
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/romi" element={<RomiPage />} />
          <Route path="/ai" element={<AiPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/settings" element={<BusinessSettingsPage />} />
          <Route path="/integrations" element={<IntegrationsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
