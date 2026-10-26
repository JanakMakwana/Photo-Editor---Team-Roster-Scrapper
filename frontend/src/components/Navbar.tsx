import React from 'react';
import { User } from '../types';
import { Layers, Shield, Building2, Users, KeyRound, LogOut, Sparkles } from 'lucide-react';

interface NavbarProps {
  user: User | null;
  onOpenTeam: () => void;
  onOpenSuperAdmin: () => void;
  onOpenAccount: () => void;
  onLogout: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  user,
  onOpenTeam,
  onOpenSuperAdmin,
  onOpenAccount,
  onLogout
}) => {
  if (!user) return null;

  const isSuperAdmin = user.is_superadmin || user.role === 'superadmin';
  const isCompanyAdmin = user.role === 'company_admin';
  const company = user.company;
  const seatPct = company ? Math.min(100, Math.round((company.used_seats / company.max_seats) * 100)) : 0;

  return (
    <nav className="saas-navbar">
      {/* Left: Brand & Organization Badges */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: 34,
            height: 34,
            borderRadius: 8,
            background: 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 4px 12px rgba(37,99,235,0.25)',
            border: '1px solid rgba(37,99,235,0.3)'
          }}>
            <Layers size={18} color="#ffffff" strokeWidth={2.2} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
            <div className="saas-brand-title">
              VeloRoster <span style={{ color: 'var(--brand-accent)' }}>AI</span>
            </div>
            <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              COMMERCIAL ATHLETIC MEDIA SUITE
            </div>
          </div>
        </div>

        {/* SuperAdmin Global Scope Badge */}
        {isSuperAdmin && (
          <div className="saas-platform-admin-badge" title="Root Platform Operator across all organizations">
            <Shield size={14} />
            <span>SuperAdmin Scope</span>
          </div>
        )}

        {/* Company Badge & Seat Meter (Client Users) */}
        {!isSuperAdmin && company && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div className="saas-company-badge">
              <Building2 size={13} />
              <span>{company.name}</span>
              <span className="saas-plan-pill">{company.plan}</span>
            </div>
            <div
              className="seat-quota-pill"
              onClick={onOpenTeam}
              title="Click to view organization members and subscription seats"
            >
              <div className="seat-mini-progress">
                <div className="seat-mini-fill" style={{ width: `${seatPct}%` }} />
              </div>
              <span>{company.used_seats} / {company.max_seats} Seats</span>
            </div>
          </div>
        )}
      </div>

      {/* Right: Actions & User Avatar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        {isSuperAdmin && (
          <button className="btn btn-secondary btn-sm" onClick={onOpenSuperAdmin}>
            <Shield size={14} color="#2563eb" />
            <span>Organization Hub</span>
          </button>
        )}

        {!isSuperAdmin && isCompanyAdmin && (
          <button className="btn btn-secondary btn-sm" onClick={onOpenTeam}>
            <Users size={14} />
            <span>Team & Seats</span>
          </button>
        )}

        <button className="btn btn-ghost btn-sm" onClick={onOpenAccount} title="Security, Credentials & Passkeys">
          <KeyRound size={14} />
          <span>Security</span>
        </button>

        <div style={{ width: 1, height: 20, background: 'var(--border-subtle)', margin: '0 4px' }} />

        {/* User Identity Chip */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{
            width: 30,
            height: 30,
            borderRadius: '50%',
            background: 'var(--bg-subtle)',
            border: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '0.78rem',
            fontWeight: 700,
            color: 'var(--brand-accent)'
          }}>
            {user.full_name ? user.full_name.charAt(0).toUpperCase() : 'U'}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1, textAlign: 'left' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text)' }}>
              {user.full_name || user.email.split('@')[0]}
            </span>
            <span style={{ fontSize: '0.66rem', color: 'var(--text-muted)' }}>
              {user.email}
            </span>
          </div>
        </div>

        <button className="btn btn-ghost btn-sm" onClick={onLogout} title="Sign Out">
          <LogOut size={15} color="#ef4444" />
        </button>
      </div>
    </nav>
  );
};
