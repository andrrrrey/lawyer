import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useMe, type UserRole } from "@/api/auth";

export function RequireRole({ roles, children }: { roles: UserRole[]; children: ReactNode }) {
  const me = useMe();
  return me.data && roles.includes(me.data.role) ? children : <Navigate to="/dashboard" replace />;
}
