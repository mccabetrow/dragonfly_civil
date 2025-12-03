import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './style.css';

const container = document.getElementById('root');

if (!container) {
  throw new Error('Failed to find the root element with id "root".');
}

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
