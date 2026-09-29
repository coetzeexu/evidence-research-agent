import { createRoot } from 'react-dom/client';
import { StandaloneReport } from './StandaloneReport';
import type { Bundle } from './types';
import './report.css';

const bundle = JSON.parse(document.getElementById('report-data')!.textContent!) as Bundle;
createRoot(document.getElementById('root')!).render(<StandaloneReport bundle={bundle} />);
