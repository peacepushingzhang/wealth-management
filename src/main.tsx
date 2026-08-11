import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import WealthPilotApp from './wealthpilot/WealthPilotApp'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <WealthPilotApp />
  </StrictMode>,
)
