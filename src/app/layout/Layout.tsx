import { Outlet, NavLink } from 'react-router-dom'
import './Layout.css'

function Layout() {
  return (
    <div className="app-layout">
      <nav className="app-nav">
        <div className="nav-brand">DDO Builder</div>
        <ul className="nav-links">
          <li><NavLink to="/" end>Home</NavLink></li>
          <li><NavLink to="/character">Character</NavLink></li>
          <li><NavLink to="/gear">Gear</NavLink></li>
        </ul>
      </nav>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}

export default Layout
