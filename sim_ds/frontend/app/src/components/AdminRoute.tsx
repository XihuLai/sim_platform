import { Navigate, Outlet } from "react-router-dom";
import { currentUser } from "../auth";

export function AdminRoute() {
  const user = currentUser();
  if (!user) return <Navigate to="/login" replace />;
  const admin = Boolean(user.admin) || user.role === "admin" || user.role === "super_admin";
  return admin ? <Outlet /> : <Navigate to="/scenarios" replace />;
}
