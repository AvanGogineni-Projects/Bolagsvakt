import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './Shell'
import { Company } from './pages/Company'
import { Login } from './pages/Login'
import { Watchlist } from './pages/Watchlist'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Shell><Watchlist /></Shell>} />
        <Route path="/company/:orgNr" element={<Shell><Company /></Shell>} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </BrowserRouter>
  )
}
