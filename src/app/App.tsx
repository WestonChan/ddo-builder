import { Routes, Route } from 'react-router-dom'
import Layout from './layout/Layout'
import Home from '../features/shared/Home'
import CharacterBuilder from '../features/character/components/CharacterBuilder'
import GearPlanner from '../features/gear/components/GearPlanner'

function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="character" element={<CharacterBuilder />} />
        <Route path="gear" element={<GearPlanner />} />
      </Route>
    </Routes>
  )
}

export default App
