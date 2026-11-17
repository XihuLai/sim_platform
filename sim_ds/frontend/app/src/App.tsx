import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RequireAuth } from "./components/RequireAuth";
import { AdminRoute } from "./components/AdminRoute";
import { Metrics } from "./pages/Metrics";
import { PlaybackPage } from "./pages/Playback";
import { QueueBoard } from "./pages/QueueBoard";
import { ScenarioCreate } from "./pages/ScenarioCreate";
import { ScenarioEdit } from "./pages/ScenarioEdit";
import { ScenarioList } from "./pages/ScenarioList";
import { Sets } from "./pages/Sets";
import { TaskDetail } from "./pages/TaskDetail";
import { TaskList } from "./pages/TaskList";
import { TaskSubmit } from "./pages/TaskSubmit";
import { TaskSummaryPage } from "./pages/TaskSummaryPage";
import { LoginPage } from "./pages/Login";
import { Users } from "./pages/Users";
import { Stats } from "./pages/Stats";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
        <Route index element={<Navigate to="/scenarios" replace />} />
        <Route path="/scenarios" element={<ScenarioList />} />
        <Route path="/scenarios/new" element={<ScenarioCreate />} />
        <Route path="/scenarios/:scenarioId/edit" element={<ScenarioEdit />} />
        <Route path="/metrics" element={<Metrics />} />
        <Route path="/sets" element={<Sets />} />
        <Route path="/tasks" element={<TaskList />} />
        <Route path="/tasks/new" element={<TaskSubmit />} />
        <Route path="/tasks/:taskId" element={<TaskDetail />} />
        <Route path="/tasks/:taskId/summary" element={<TaskSummaryPage />} />
        <Route path="/queue" element={<QueueBoard />} />
        <Route path="/stats" element={<Stats />} />
        <Route path="/playback" element={<PlaybackPage />} />
        <Route element={<AdminRoute />}>
          <Route path="/admin/users" element={<Users />} />
        </Route>
        <Route path="*" element={<Navigate to="/scenarios" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
