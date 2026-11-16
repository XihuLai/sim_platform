import { Navigate, Outlet } from "react-router-dom";
import { getToken } from "../auth";

export function RequireAuth() {
  return getToken() ? <Outlet /> : <Navigate to="/login" replace />;
}
