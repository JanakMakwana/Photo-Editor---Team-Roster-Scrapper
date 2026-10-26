import React, { useState, useEffect } from 'react';
import { User, Player } from './types';
import { Navbar } from './components/Navbar';
import { AuthGateway } from './components/AuthGateway';
import { AthleteSearch } from './components/AthleteSearch';
import { TeamRosterScraper } from './components/TeamRosterScraper';
import { StudioWorkbench } from './components/StudioWorkbench';
import { SuperAdminModal } from './components/SuperAdminModal';
import { TeamModal } from './components/TeamModal';
import { AccountModal } from './components/AccountModal';
import { Search, Globe, SlidersHorizontal } from 'lucide-react';

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authChecking, setAuthChecking] = useState(true);

  // Workflow navigation
  const [activeTab, setActiveTab] = useState<'search' | 'roster' | 'workbench'>('search');

  // Workbench shared state
  const [workbenchPlayer, setWorkbenchPlayer] = useState<Player | null>(null);
  const [workbenchRoster, setWorkbenchRoster] = useState<Player[]>([]);

  // Modals state
  const [superAdminOpen, setSuperAdminOpen] = useState(false);
  const [teamOpen, setTeamOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);

  // Initial Auth Check
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const res = await fetch('/api/auth/me');
        const data = await res.json();
        if (res.ok && data.logged_in && data.user) {
          setUser(data.user);
        } else {
          setUser(null);
        }
      } catch (e) {
        setUser(null);
      } finally {
        setAuthChecking(false);
      }
    };
    checkAuth();
  }, []);

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
    setUser(null);
  };

  const handleTuneInWorkbench = (playerData: { name: string; url: string }) => {
    setWorkbenchPlayer({
      name: playerData.name.replace(/\.[^.]+$/, ''),
      image: playerData.url
    });
    setActiveTab('workbench');
  };

  const handleLoadRosterInWorkbench = (players: Player[], folderName: string) => {
    setWorkbenchRoster(players);
    if (players.length > 0) {
      setWorkbenchPlayer(players[0]);
    }
    setActiveTab('workbench');
  };

  const handleTuneSingleInWorkbench = (player: Player) => {
    setWorkbenchPlayer(player);
    setActiveTab('workbench');
  };

  if (authChecking) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: '0.9rem', fontWeight: 600 }}>Loading VeloRoster AI...</div>
      </div>
    );
  }

  // Not logged in -> Show Enterprise Gateway
  if (!user) {
    return <AuthGateway onLoginSuccess={setUser} />;
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Global SaaS Navbar */}
      <Navbar
        user={user}
        onOpenSuperAdmin={() => setSuperAdminOpen(true)}
        onOpenTeam={() => setTeamOpen(true)}
        onOpenAccount={() => setAccountOpen(true)}
        onLogout={handleLogout}
      />

      {/* Main Content Area */}
      <main style={{ flex: 1, padding: '24px 20px', maxWidth: 1200, width: '100%', margin: '0 auto' }}>
        {/* Workflow Segmented Navigation Tabs */}
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 28 }}>
          <div className="workflow-segmented-bar">
            <button
              className={`workflow-tab-btn ${activeTab === 'search' ? 'active' : ''}`}
              onClick={() => setActiveTab('search')}
            >
              <Search size={15} />
              <span>Single Athlete Search</span>
            </button>
            <button
              className={`workflow-tab-btn ${activeTab === 'roster' ? 'active' : ''}`}
              onClick={() => setActiveTab('roster')}
            >
              <Globe size={15} />
              <span>Full Team Roster Scraper</span>
            </button>
            <button
              className={`workflow-tab-btn ${activeTab === 'workbench' ? 'active' : ''}`}
              onClick={() => setActiveTab('workbench')}
            >
              <SlidersHorizontal size={15} />
              <span>180×180 Studio Workbench</span>
            </button>
          </div>
        </div>

        {/* View Switcher */}
        {activeTab === 'search' && (
          <AthleteSearch onTuneInWorkbench={handleTuneInWorkbench} />
        )}

        {activeTab === 'roster' && (
          <TeamRosterScraper
            onLoadRosterInWorkbench={handleLoadRosterInWorkbench}
            onTuneSingleInWorkbench={handleTuneSingleInWorkbench}
          />
        )}

        {activeTab === 'workbench' && (
          <StudioWorkbench
            initialPlayer={workbenchPlayer}
            rosterList={workbenchRoster}
          />
        )}
      </main>

      {/* Footer */}
      <footer style={{
        padding: '24px 20px',
        borderTop: '1px solid var(--border-subtle)',
        fontSize: '0.76rem',
        color: 'var(--text-muted)',
        textAlign: 'center',
        background: '#ffffff'
      }}>
        <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>
          VeloRoster AI™ &bull; Developed by Ecstaticloud Technologies
        </div>
        <div>
          Proprietary athletic roster ingestion, player number assignment, and 180×180 headshot standardization.
        </div>
        <div style={{ fontSize: '0.7rem', color: 'var(--text-disabled)', marginTop: 4 }}>
          &copy; 2026 Ecstaticloud Technologies. All Rights Reserved.
        </div>
      </footer>

      {/* Modals */}
      <SuperAdminModal
        isOpen={superAdminOpen}
        onClose={() => setSuperAdminOpen(false)}
      />

      <TeamModal
        isOpen={teamOpen}
        onClose={() => setTeamOpen(false)}
        currentUser={user}
      />

      <AccountModal
        isOpen={accountOpen}
        onClose={() => setAccountOpen(false)}
        currentUser={user}
        onUserUpdated={setUser}
      />
    </div>
  );
}

export default App;
