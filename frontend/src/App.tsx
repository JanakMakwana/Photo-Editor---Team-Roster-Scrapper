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

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authChecking, setAuthChecking] = useState(true);

  // Workflow navigation: 'workbench' | 'search' | 'roster'
  const [activeTab, setActiveTab] = useState<'workbench' | 'search' | 'roster'>('workbench');

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
        <div style={{ fontSize: '0.875rem', fontWeight: 600 }}>Loading VeloRoster AI...</div>
      </div>
    );
  }

  // Not logged in -> Show Clean Enterprise Gateway
  if (!user) {
    return <AuthGateway onLoginSuccess={setUser} />;
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-app)' }}>
      {/* Sleek Header with integrated tab navigation */}
      <Navbar
        user={user}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onOpenSuperAdmin={() => setSuperAdminOpen(true)}
        onOpenTeam={() => setTeamOpen(true)}
        onOpenAccount={() => setAccountOpen(true)}
        onLogout={handleLogout}
      />

      {/* Main Workspace Area */}
      <main style={{ flex: 1, padding: '32px 24px', maxWidth: 1240, width: '100%', margin: '0 auto' }}>
        {activeTab === 'workbench' && (
          <StudioWorkbench
            initialPlayer={workbenchPlayer}
            rosterList={workbenchRoster}
          />
        )}

        {activeTab === 'search' && (
          <AthleteSearch onTuneInWorkbench={handleTuneInWorkbench} />
        )}

        {activeTab === 'roster' && (
          <TeamRosterScraper
            onLoadRosterInWorkbench={handleLoadRosterInWorkbench}
            onTuneSingleInWorkbench={handleTuneSingleInWorkbench}
          />
        )}
      </main>

      {/* Footer */}
      <footer style={{
        padding: '20px 24px',
        borderTop: '1px solid var(--border)',
        fontSize: '0.8125rem',
        color: 'var(--text-muted)',
        textAlign: 'center',
        background: '#ffffff'
      }}>
        <div>VeloRoster AI &bull; Commercial Edition &bull; Ecstaticloud Technologies</div>
      </footer>

      {/* Modals */}
      {superAdminOpen && (
        <SuperAdminModal onClose={() => setSuperAdminOpen(false)} />
      )}

      {teamOpen && (
        <TeamModal user={user} onClose={() => setTeamOpen(false)} />
      )}

      {accountOpen && (
        <AccountModal user={user} onClose={() => setAccountOpen(false)} />
      )}
    </div>
  );
}

export default App;
