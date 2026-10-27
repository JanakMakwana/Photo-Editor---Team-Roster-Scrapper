import React, { useState, useEffect } from 'react';
import { Company } from '../types';
import { Shield, Plus, Building2, Users, X, Check } from 'lucide-react';

interface SuperAdminModalProps {
  isOpen?: boolean;
  onClose: () => void;
}

export const SuperAdminModal: React.FC<SuperAdminModalProps> = ({ isOpen = true, onClose }) => {
  const [tab, setTab] = useState<'companies' | 'create'>('companies');
  const [metrics, setMetrics] = useState<any | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(false);

  // New Organization Form
  const [name, setName] = useState('');
  const [plan, setPlan] = useState('team');
  const [maxSeats, setMaxSeats] = useState(15);
  const [adminEmail, setAdminEmail] = useState('');
  const [adminName, setAdminName] = useState('');
  const [createMsg, setCreateMsg] = useState('');

  const fetchStats = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/admin/dashboard_stats');
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setMetrics(data.metrics);
        setCompanies(data.metrics.companies || []);
      }
    } catch (e) {
      console.error('Failed to load superadmin stats', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchStats();
    }
  }, [isOpen]);

  const handleCreateCompany = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateMsg('');
    try {
      const res = await fetch('/api/admin/companies/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          plan,
          max_seats: Number(maxSeats),
          admin_email: adminEmail.trim(),
          admin_name: adminName.trim()
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setCreateMsg(`Created organization '${data.company.name}' successfully!`);
        setName('');
        setAdminEmail('');
        setAdminName('');
        fetchStats();
        setTimeout(() => setTab('companies'), 1200);
      } else {
        alert(data.detail || data.message || 'Failed to create organization');
      }
    } catch (e: any) {
      alert(`Error: ${e.message}`);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-card" style={{ maxWidth: 900 }}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 34,
              height: 34,
              borderRadius: 8,
              background: '#eff6ff',
              border: '1px solid #bfdbfe',
              color: '#1d4ed8',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Shield size={18} />
            </div>
            <div>
              <h3 className="modal-title">SUPERADMIN PLATFORM FLEET HUB</h3>
              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Organization Management & Seat Allocation</p>
            </div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="modal-body">
          {/* Top KPI Metrics Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 20 }}>
            <div className="saas-card" style={{ padding: 16 }}>
              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 600 }}>Total Organizations</div>
              <div style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--text)' }}>
                {metrics?.total_companies ?? companies.length}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--success)' }}>Active Licensed Companies</div>
            </div>

            <div className="saas-card" style={{ padding: 16 }}>
              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 600 }}>Allocated Seat Capacity</div>
              <div style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--brand-accent)' }}>
                {metrics?.total_seats_allocated ?? 0}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Total User Seats Provisioned</div>
            </div>

            <div className="saas-card" style={{ padding: 16 }}>
              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 600 }}>Active Seated Users</div>
              <div style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--text)' }}>
                {metrics?.total_used_seats ?? 0}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Occupied Enterprise Seats</div>
            </div>
          </div>

          {/* Tab Switcher */}
          <div className="workflow-segmented-bar" style={{ marginBottom: 18 }}>
            <button
              className={`workflow-tab-btn ${tab === 'companies' ? 'active' : ''}`}
              onClick={() => setTab('companies')}
            >
              <Building2 size={14} />
              <span>Organizations ({companies.length})</span>
            </button>
            <button
              className={`workflow-tab-btn ${tab === 'create' ? 'active' : ''}`}
              onClick={() => setTab('create')}
            >
              <Plus size={14} />
              <span>+ Provision New Organization</span>
            </button>
          </div>

          {/* View 1: Companies Table */}
          {tab === 'companies' && (
            <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
              <table className="saas-table">
                <thead>
                  <tr>
                    <th>Organization</th>
                    <th>Plan Tier</th>
                    <th>Seat Capacity</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {companies.map((c) => {
                    const pct = Math.min(100, Math.round(((c.used_seats || 0) / (c.max_seats || 10)) * 100));
                    return (
                      <tr key={c.id}>
                        <td>
                          <div style={{ fontWeight: 700, fontSize: '0.86rem' }}>{c.name}</div>
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>slug: {c.slug}</div>
                        </td>
                        <td>
                          <span className="saas-plan-pill">{c.plan}</span>
                        </td>
                        <td>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.74rem', marginBottom: 4 }}>
                            <span>{c.used_seats || 0} Seated</span>
                            <span style={{ color: 'var(--text-muted)' }}>{c.max_seats} Max</span>
                          </div>
                          <div style={{ width: 140, height: 6, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden' }}>
                            <div style={{ width: `${pct}%`, height: '100%', background: 'var(--brand-accent)' }} />
                          </div>
                        </td>
                        <td>
                          <span style={{ fontSize: '0.72rem', color: 'var(--success)', fontWeight: 700 }}>
                            {c.status || 'Active'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* View 2: Provision Company Form */}
          {tab === 'create' && (
            <form onSubmit={handleCreateCompany} style={{ maxWidth: 500, margin: '0 auto', textAlign: 'left' }}>
              <div className="saas-form-group">
                <label className="saas-form-label">Organization Name</label>
                <input
                  type="text"
                  className="saas-input"
                  placeholder="e.g. Manchester Storm Athletics"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div className="saas-form-group">
                  <label className="saas-form-label">Subscription Tier</label>
                  <select
                    className="saas-input"
                    value={plan}
                    onChange={(e) => setPlan(e.target.value)}
                  >
                    <option value="team">Team (Commercial)</option>
                    <option value="enterprise">Enterprise</option>
                    <option value="free">Evaluation</option>
                  </select>
                </div>

                <div className="saas-form-group">
                  <label className="saas-form-label">Licensed Seats</label>
                  <input
                    type="number"
                    className="saas-input"
                    min={1}
                    max={500}
                    value={maxSeats}
                    onChange={(e) => setMaxSeats(Number(e.target.value))}
                    required
                  />
                </div>
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Initial Organization Admin Email (Optional)</label>
                <input
                  type="email"
                  className="saas-input"
                  placeholder="admin@organization.com"
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                />
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Admin Full Name</label>
                <input
                  type="text"
                  className="saas-input"
                  placeholder="e.g. Jordan Miller"
                  value={adminName}
                  onChange={(e) => setAdminName(e.target.value)}
                />
              </div>

              {createMsg && (
                <div style={{
                  padding: '10px 14px',
                  background: 'var(--success-subtle)',
                  border: '1px solid var(--success-border)',
                  color: 'var(--success)',
                  borderRadius: 'var(--r-md)',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  marginBottom: 16
                }}>
                  {createMsg}
                </div>
              )}

              <button
                type="submit"
                className="btn btn-primary"
                style={{ width: '100%', padding: '11px' }}
              >
                <span>Provision Organization</span>
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
