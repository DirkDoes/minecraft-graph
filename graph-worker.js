import { layoutGraph } from './core.mjs';
self.onmessage = ({ data }) => {
  try { self.postMessage(layoutGraph(data.nodes, data.edges, { mode: data.mode, selected: data.selected })); }
  catch (error) { self.postMessage({ error: error.message }); }
};
