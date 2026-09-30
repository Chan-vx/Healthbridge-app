"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearSession, getSession, HOME, Role, User } from "@/lib/api";

const NAV: Record<Role, { href: string; label: string }[]> = {
  patient: [
    { href: "/patient", label: "Overview" },
    { href: "/patient/estimate", label: "Cost estimate" },
    { href: "/bills", label: "My bills" },
    { href: "/claims", label: "Claims" },
  ],
  hospital: [
    { href: "/hospital", label: "Overview" },
    { href: "/bills", label: "Bills" },
    { href: "/claims", label: "Claims" },
  ],
  insurer: [
    { href: "/insurance", label: "Overview" },
    { href: "/claims", label: "Claims queue" },
    { href: "/insurance/policies", label: "Policies" },
  ],
  finance: [
    { href: "/finance", label: "Finance" },
    { href: "/bills", label: "Bills" },
    { href: "/claims", label: "Claims" },
  ],
  admin: [
    { href: "/admin", label: "Admin" },
    { href: "/finance", label: "Finance" },
    { href: "/bills", label: "Bills" },
    { href: "/claims", label: "Claims" },
  ],
};

const ROLE_LABEL: Record<Role, string> = {
  patient: "Patient",
  hospital: "Hospital",
  insurer: "Insurance",
  finance: "Finance",
  admin: "Administrator",
};

export default function AppShell({ roles, children }: { roles: Role[]; children: (user: User) => React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const allowed = roles.join(",");

  useEffect(() => {
    const session = getSession();
    if (!session) {
      router.replace("/login");
      return;
    }
    if (!allowed.split(",").includes(session.user.role)) {
      router.replace(HOME[session.user.role]);
      return;
    }
    setUser(session.user);
  }, [allowed, router]);

  if (!user) return null;

  const logout = () => {
    clearSession();
    router.replace("/login");
  };

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <div className="brand-mark" aria-hidden>H</div>
          <div>
            <div className="brand-name">HealthBridge</div>
            <div className="brand-sub">{ROLE_LABEL[user.role]} workspace</div>
          </div>
        </div>
        <nav className="nav" aria-label="Main">
          {NAV[user.role].map((item) => {
            const active = item.href === pathname || (item.href !== HOME[user.role] && pathname.startsWith(item.href));
            return (
              <Link key={item.href} href={item.href} className={active ? "active" : undefined}>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="side-foot">
          <div>
            <div className="who">{user.full_name}</div>
            <div className="role">{user.email}</div>
          </div>
          <button className="btn ghost small" onClick={logout}>Log out</button>
        </div>
      </aside>
      <main className="main">{children(user)}</main>
    </div>
  );
}
