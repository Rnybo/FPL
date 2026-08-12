import { NavLink, Route, Routes } from 'react-router-dom'
import PlayerScout from './pages/PlayerScout'
import SquadBuilder from './pages/SquadBuilder'
import ComingSoon from './pages/ComingSoon'

const NAV = [
  { to: '/', label: 'Player Scout' },
  { to: '/squad', label: 'Squad Builder' },
  { to: '/league', label: 'League Hub' },
  { to: '/team', label: 'My Team' },
  { to: '/fixtures', label: 'Fixtures' },
  { to: '/model', label: 'Model Transparency' },
]

function Nav() {
  return (
    <nav className="border-b border-slate-200 bg-white overflow-x-auto">
      <div className="max-w-5xl mx-auto flex gap-1 px-3 sm:px-6 flex-nowrap w-max sm:w-auto">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `px-2.5 sm:px-3 py-3 text-sm font-medium border-b-2 -mb-px whitespace-nowrap ${
                isActive
                  ? 'border-emerald-600 text-emerald-700'
                  : 'border-transparent text-slate-500 hover:text-slate-800'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <Nav />
      <Routes>
        <Route path="/" element={<PlayerScout />} />
        <Route path="/squad" element={<SquadBuilder />} />
        <Route path="/league" element={<ComingSoon title="League Hub" />} />
        <Route path="/team" element={<ComingSoon title="My Team" />} />
        <Route path="/fixtures" element={<ComingSoon title="Fixtures" />} />
        <Route path="/model" element={<ComingSoon title="Model Transparency" />} />
      </Routes>
    </div>
  )
}
