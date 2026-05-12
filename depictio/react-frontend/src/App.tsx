import { Navigate, Route, Routes } from "react-router-dom";
import AuthPage from "./pages/AuthPage";
import DashboardsPage from "./pages/DashboardsPage";
import ProtectedRoute from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboards" replace />} />
      <Route path="/auth" element={<AuthPage />} />
      <Route
        path="/dashboards"
        element={
          <ProtectedRoute>
            <DashboardsPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/dashboards" replace />} />
    </Routes>
  );
}
