import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivitySquare, CircleAlert, PhoneCall, RefreshCcw } from 'lucide-react';
import PageHeader from '../components/PageHeader';
import SectionHeader from '../components/SectionHeader';
import MetricsGate from '../components/MetricsGate';
import StatusMessage from '../components/StatusMessage';
import RefreshButton from '../components/RefreshButton';
import { useOpsConsole } from '../hooks/useOpsConsole';
import type { OpsCallTask, OpsConsoleSnapshot } from '../hooks/useOpsConsole';
import { useOpsPlaintiffProfile } from '../hooks/useOpsPlaintiffProfile';
import type { OpsPlaintiffProfile } from '../hooks/useOpsPlaintiffProfile';
import { supabaseClient } from '../lib/supabaseClient';
import { formatCurrency, formatDateTime } from '../utils/formatters';
import CallQueuePanel from '../components/CallQueuePanel';
import { useOpsDailySummary } from '../hooks/useOpsDailySummary';
import type { OpsDailySummary } from '../hooks/useOpsDailySummary';

const QUICK_ACTIONS: Array<{
	key: string;
	label: string;
	outcome: CallOutcomeValue;
	followUpDays?: number;
	helper: string;
}> = [
	{ key: 'reached', label: 'Reached', outcome: 'reached', helper: 'Spoke with plaintiff or firm.' },
	{ key: 'no_answer', label: 'No answer', outcome: 'no_answer', helper: 'Rang but nobody picked up.' },
	{ key: 'bad_number', label: 'Wrong number', outcome: 'bad_number', helper: 'Line disconnected or wrong contact.' },
	{
		key: 'follow_up',
		label: 'Follow-up',
		outcome: 'left_voicemail',
		followUpDays: 2,
		helper: 'Left voicemail — remind yourself to retry.',
	},
];

const CALL_OUTCOME_OPTIONS: Array<{ value: CallOutcomeValue; label: string }> = [
	{ value: 'reached', label: 'Reached' },
	{ value: 'left_voicemail', label: 'Left voicemail' },
	{ value: 'no_answer', label: 'No answer' },
	{ value: 'bad_number', label: 'Wrong number' },
	{ value: 'do_not_call', label: 'Do not call' },
];

const INTEREST_OPTIONS: Array<{ value: InterestLevel; label: string }> = [
	{ value: 'hot', label: 'Hot' },
	{ value: 'warm', label: 'Warm' },
	{ value: 'cold', label: 'Cold' },
	{ value: 'none', label: 'None' },
];

const ENFORCEMENT_STAGE_OPTIONS = [
	{ value: 'pre_enforcement', label: 'Pre-enforcement' },
	{ value: 'paperwork_filed', label: 'Paperwork filed' },
	{ value: 'levy_issued', label: 'Levy issued' },
	{ value: 'payment_plan', label: 'Payment plan' },
	{ value: 'waiting_payment', label: 'Waiting payment' },
	{ value: 'collected', label: 'Collected' },
	{ value: 'closed_no_recovery', label: 'Closed – no recovery' },
];

type CallOutcomeValue = 'reached' | 'left_voicemail' | 'no_answer' | 'bad_number' | 'do_not_call';
type InterestLevel = 'hot' | 'warm' | 'cold' | 'none';

type CallOutcomePayload = {
	outcome: CallOutcomeValue;
	interest: InterestLevel;
	notes: string;
	followUp: string;
};

export function OpsConsolePage() {
	const { state, data, refetch, lastUpdated, removeTask } = useOpsConsole();
	const dailySummary = useOpsDailySummary();
	const tasks = data?.tasks ?? [];
	const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
	const [drawerOpen, setDrawerOpen] = useState(false);
	const [drawerPreset, setDrawerPreset] = useState<{ outcome?: CallOutcomeValue; followUp?: string }>({});
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [formError, setFormError] = useState<string | null>(null);
	const [toastMessage, setToastMessage] = useState<string | null>(null);

	const selectedTask: OpsCallTask | null = useMemo(() => {
		if (selectedTaskId) {
			return tasks.find((task) => task.taskId === selectedTaskId) ?? null;
		}
		return data?.nextBestTask ?? tasks[0] ?? null;
	}, [tasks, selectedTaskId, data]);

	useEffect(() => {
		if (state.status === 'ready' && data?.nextBestTask && !selectedTaskId) {
			setSelectedTaskId(data.nextBestTask.taskId);
		}
	}, [state.status, data, selectedTaskId]);

	useEffect(() => {
		if (selectedTaskId && tasks.every((task) => task.taskId !== selectedTaskId)) {
			setSelectedTaskId(tasks[0]?.taskId ?? null);
		}
	}, [tasks, selectedTaskId]);

	const profile = useOpsPlaintiffProfile(selectedTask?.plaintiffId ?? null);

	const openDrawer = useCallback(
		(task: OpsCallTask, preset?: { outcome?: CallOutcomeValue; followUp?: string }) => {
			setSelectedTaskId(task.taskId);
			setDrawerPreset(preset ?? {});
			setFormError(null);
			setDrawerOpen(true);
		},
		[],
	);

	const closeDrawer = useCallback(() => {
		if (isSubmitting) {
			return;
		}
		setDrawerOpen(false);
		setFormError(null);
		setDrawerPreset({});
	}, [isSubmitting]);

	const handleSubmitOutcome = useCallback(
		async (payload: CallOutcomePayload) => {
			if (!selectedTask) {
				return;
			}

			setIsSubmitting(true);
			setFormError(null);

			let followUpIso: string | null = null;
			if (payload.followUp) {
				const parsed = Date.parse(payload.followUp);
				if (Number.isNaN(parsed)) {
					setFormError('Follow-up timestamp is invalid. Use YYYY-MM-DDTHH:MM.');
					setIsSubmitting(false);
					return;
				}
				followUpIso = new Date(parsed).toISOString();
			}

			try {
				const { error } = await supabaseClient.rpc('log_call_outcome', {
					_plaintiff_id: selectedTask.plaintiffId,
					_task_id: selectedTask.taskId,
					_outcome: payload.outcome,
					_interest: payload.interest,
					_notes: payload.notes.trim() ? payload.notes.trim() : null,
					_follow_up_at: followUpIso,
				});

				if (error) {
					throw error;
				}

				removeTask(selectedTask.taskId);
				await Promise.all([refetch(), profile.refetch()]);
				setDrawerOpen(false);
				setDrawerPreset({});
				setToastMessage('Call outcome logged.');
			} catch (err) {
				setFormError(err instanceof Error ? err.message : 'Unable to log call outcome.');
			} finally {
				setIsSubmitting(false);
			}
		},
		[selectedTask, removeTask, refetch, profile],
	);

	useEffect(() => {
		if (!toastMessage) {
			return undefined;
		}
		const timer = window.setTimeout(() => setToastMessage(null), 3500);
		return () => window.clearTimeout(timer);
	}, [toastMessage]);

	const handleQuickAction = useCallback(
		(task: OpsCallTask, action: { outcome: CallOutcomeValue; followUpDays?: number }) => {
			const presetFollowUp = action.followUpDays ? formatDatetimeLocal(addDays(action.followUpDays)) : undefined;
			openDrawer(task, { outcome: action.outcome, followUp: presetFollowUp });
		},
		[openDrawer],
	);

	return (
		<div className="space-y-8">
			<PageHeader
				eyebrow="Operations"
				title="Ops console"
				subtitle="Work today’s outreach, log dispositions, and keep enforcement current in one screen."
			/>

			<DailySummarySection summaryHook={dailySummary} />

			<CallQueuePanel />

			{toastMessage ? <Toast message={toastMessage} /> : null}

			<div className="grid gap-8 xl:grid-cols-[2fr,1fr]">
				<div className="space-y-6">
					<section className="df-card space-y-4">
						<SectionHeader
							eyebrow="Tasks"
							title="Today’s call queue"
							description="Pulls from v_plaintiff_call_queue and auto-sorts using recency, tier, and due date."
							actions={
								<RefreshButton
									onClick={() => void refetch()}
									isLoading={state.status === 'loading'}
									hasData={!!data?.tasks?.length}
								/>
							}
						/>
						<MetricsGate
							state={state}
							errorTitle="Call queue unavailable"
							onRetry={() => void refetch()}
							ready={
								<TodayTasksPanel
									snapshot={data ?? buildEmptySnapshot()}
									tasks={tasks}
									selectedTaskId={selectedTask?.taskId ?? null}
									onSelectTask={(taskId) => setSelectedTaskId(taskId)}
									onQuickAction={(task, action) => handleQuickAction(task, action)}
								/>
							}
							loadingFallback={<StatusMessage tone="info">Loading call queue…</StatusMessage>}
						/>
					</section>

					<CallDispositionPanel
						task={selectedTask}
						onOpenForm={(preset) => selectedTask && openDrawer(selectedTask, preset)}
					/>
				</div>

				<aside className="space-y-6">
					<MetricsSidebar metrics={data?.pipelineMetrics ?? []} lastUpdated={lastUpdated} queueSnapshot={data ?? undefined} />
					<PlaintiffProfilePanel
						profileHook={profile}
						selectedTask={selectedTask}
						onStageSaved={() => void profile.refetch()}
					/>
				</aside>
			</div>

			<CallOutcomeDrawer
				isOpen={drawerOpen && !!selectedTask}
				task={selectedTask}
				presetOutcome={drawerPreset.outcome}
				presetFollowUp={drawerPreset.followUp}
				isSubmitting={isSubmitting}
				errorMessage={formError}
				onClose={closeDrawer}
				onSubmit={handleSubmitOutcome}
			/>
		</div>
	);
}

type DailySummarySectionProps = {
	summaryHook: ReturnType<typeof useOpsDailySummary>;
};

function DailySummarySection({ summaryHook }: DailySummarySectionProps) {
	return (
		<section className="df-card space-y-4">
			<SectionHeader
				eyebrow="Today"
				title="Daily progress snapshot"
				description="Pulled from v_ops_daily_summary so everyone sees the same scoreboard."
				actions={
					<RefreshButton
						onClick={() => void summaryHook.refetch()}
						isLoading={summaryHook.state.status === 'loading'}
						hasData={!!summaryHook.state.data}
					/>
				}
			/>
			<MetricsGate
				state={summaryHook.state}
				errorTitle="Daily summary unavailable"
				onRetry={() => void summaryHook.refetch()}
				ready={<DailySummaryGrid summary={summaryHook.state.data} />}
				loadingFallback={<StatusMessage tone="info">Loading daily summary…</StatusMessage>}
			/>
		</section>
	);
}

function DailySummaryGrid({ summary }: { summary: OpsDailySummary | null }) {
	if (!summary) {
		return <StatusMessage tone="info">No activity logged yet today.</StatusMessage>;
	}

	const metrics: Array<{ label: string; value: number; helper: string }> = [
		{ label: 'New plaintiffs', value: summary.newPlaintiffs, helper: 'Imported today' },
		{ label: 'Plaintiffs contacted', value: summary.plaintiffsContacted, helper: 'Reached via calls or status updates' },
		{ label: 'Calls made', value: summary.callsMade, helper: 'Logged attempts today' },
		{ label: 'Agreements sent', value: summary.agreementsSent, helper: 'Docs sent for signature' },
		{ label: 'Agreements signed', value: summary.agreementsSigned, helper: 'Fully signed today' },
	];

	return (
		<div className="grid gap-3 md:grid-cols-3 lg:grid-cols-5">
			{metrics.map((metric) => (
				<div key={metric.label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
					<p className="text-xs uppercase tracking-wide text-slate-500">{metric.label}</p>
					<p className="mt-1 text-2xl font-semibold text-slate-900">{metric.value.toLocaleString()}</p>
					<p className="text-xs text-slate-500">{metric.helper}</p>
				</div>
			))}
		</div>
	);
}

type TodayTasksProps = {
	snapshot: OpsConsoleSnapshot;
	tasks: OpsCallTask[];
	selectedTaskId: string | null;
	onSelectTask: (taskId: string) => void;
	onQuickAction: (task: OpsCallTask, action: { outcome: CallOutcomeValue; followUpDays?: number }) => void;
};


function TodayTasksPanel({ snapshot, tasks, selectedTaskId, onSelectTask, onQuickAction }: TodayTasksProps) {
	if (!tasks.length) {
		return <StatusMessage tone="success">No due calls right now. Fresh queue!</StatusMessage>;
	}

	return (
		<div className="space-y-4">
			<StatusMessage tone="info">
				{snapshot.overdue > 0 ? `${snapshot.overdue} overdue` : 'No overdue calls'} · {snapshot.dueToday} due today
			</StatusMessage>
			<div className="overflow-hidden rounded-2xl border border-slate-200">
				<table className="min-w-full divide-y divide-slate-200 text-sm">
					<thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
						<tr>
							<th className="px-4 py-3 text-left">Plaintiff</th>
							<th className="px-4 py-3 text-left">Tier</th>
							<th className="px-4 py-3 text-left">Phone</th>
							<th className="px-4 py-3 text-left">Due</th>
							<th className="px-4 py-3 text-left">Last contact</th>
							<th className="px-4 py-3 text-left">Priority</th>
							<th className="px-4 py-3 text-left">Actions</th>
						</tr>
					</thead>
					<tbody className="divide-y divide-slate-100">
						{tasks.map((task) => (
							<tr
								key={task.taskId}
								className={`transition hover:bg-slate-50 ${selectedTaskId === task.taskId ? 'bg-slate-100/80' : ''}`}
								onClick={() => onSelectTask(task.taskId)}
							>
								<td className="px-4 py-3">
									<p className="font-semibold text-slate-900">{task.plaintiffName}</p>
									<p className="text-xs text-slate-500">Task #{task.taskId.slice(0, 6)}</p>
								</td>
								<td className="px-4 py-3">
									<TierBadge tier={task.tier} />
								</td>
								<td className="px-4 py-3 font-mono text-sm text-slate-800">{task.phone ?? '—'}</td>
								<td className="px-4 py-3 text-sm text-slate-900">{renderDue(task.dueAt)}</td>
								<td className="px-4 py-3 text-sm text-slate-900">{renderLastContact(task.lastContactAt)}</td>
								<td className="px-4 py-3 text-xs text-slate-600">
									<span className="rounded-full bg-slate-900/5 px-2 py-1 font-semibold text-slate-900">
										Score {Math.round(task.priorityScore)}
									</span>
								</td>
								<td className="px-4 py-3">
									<div className="flex flex-wrap gap-2">
										{QUICK_ACTIONS.map((action) => (
											<button
												key={`${task.taskId}-${action.key}`}
												type="button"
												className="rounded-full border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
												onClick={(event) => {
													event.stopPropagation();
													onQuickAction(task, action);
												}}
											>
												{action.label}
											</button>
										))}
									</div>
								</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
		</div>
	);
}

type CallDispositionProps = {
	task: OpsCallTask | null;
	onOpenForm: (preset?: { outcome?: CallOutcomeValue; followUp?: string }) => void;
};

function CallDispositionPanel({ task, onOpenForm }: CallDispositionProps) {
	return (
		<section className="df-card space-y-4">
			<SectionHeader
				 eyebrow="Call disposition"
				 title="Log today’s calls"
				 description="Buttons feed the log_call_outcome RPC, update the queue, and drive plaintiff history."
			/>

			{task ? (
				<div className="space-y-3">
					<div className="rounded-2xl border border-slate-200 bg-white p-4">
						<p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected plaintiff</p>
						<p className="text-lg font-semibold text-slate-900">{task.plaintiffName}</p>
						<p className="text-sm text-slate-600">
							Tier {task.tier ?? '—'} · {task.phone ?? 'No phone on file'} · Due {renderDue(task.dueAt)}
						</p>
					</div>

					<div className="grid gap-3 md:grid-cols-2">
						{QUICK_ACTIONS.map((action) => (
							<button
								key={action.key}
								type="button"
								className="flex flex-col rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left text-sm font-semibold text-slate-800 shadow-sm transition hover:border-slate-300"
								onClick={() =>
									onOpenForm({
										outcome: action.outcome,
										followUp: action.followUpDays ? formatDatetimeLocal(addDays(action.followUpDays)) : undefined,
									})
								}
							>
								{action.label}
								<span className="text-xs font-normal text-slate-500">{action.helper}</span>
							</button>
						))}
					</div>

					<button
						type="button"
						className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-sm transition hover:bg-slate-800"
						onClick={() => onOpenForm()}
					>
						<PhoneCall className="h-4 w-4" aria-hidden="true" />
						Open full form
					</button>
				</div>
			) : (
				<StatusMessage tone="info">Select a task to log the outcome.</StatusMessage>
			)}
		</section>
	);
}

type MetricsSidebarProps = {
	metrics: OpsConsoleSnapshot['pipelineMetrics'];
	lastUpdated: string | null;
	queueSnapshot: OpsConsoleSnapshot | undefined;
};

function MetricsSidebar({ metrics, lastUpdated, queueSnapshot }: MetricsSidebarProps) {
	return (
		<section className="df-card space-y-4">
			<SectionHeader
				 eyebrow="Pipeline"
				 title="Enforcement at a glance"
				 description="Aggregated from v_enforcement_overview."
			/>
			<div className="space-y-3">
				{metrics.length === 0 ? (
					<StatusMessage tone="info">No enforcement stages recorded yet.</StatusMessage>
				) : (
					metrics.map((metric) => (
						<div key={metric.stage} className="flex items-center justify-between rounded-2xl border border-slate-200 px-4 py-3">
							<div>
								<p className="text-sm font-semibold text-slate-900">{metric.label}</p>
								<p className="text-xs text-slate-500">{metric.caseCount.toLocaleString()} plaintiffs</p>
							</div>
							<p className="text-sm font-semibold text-slate-900">{formatCurrency(metric.totalJudgmentAmount)}</p>
						</div>
					))
				)}
			</div>
			<StatusMessage tone="info">
				<span className="inline-flex items-center gap-2">
					<RefreshCcw className="h-4 w-4" aria-hidden="true" />
					Queue refreshed {formatDateTime(lastUpdated)} · {queueSnapshot?.tasks.length ?? 0} calls tracked
				</span>
			</StatusMessage>
		</section>
	);
}

type PlaintiffProfilePanelProps = {
	profileHook: ReturnType<typeof useOpsPlaintiffProfile>;
	selectedTask: OpsCallTask | null;
	onStageSaved: () => void;
};

function PlaintiffProfilePanel({ profileHook, selectedTask, onStageSaved }: PlaintiffProfilePanelProps) {
	return (
		<section className="df-card space-y-4">
			<SectionHeader
				 eyebrow="Profile"
				 title="Plaintiff timeline"
				 description="Combines call attempts, status history, and enforcement changes."
			/>
			<MetricsGate
				 state={profileHook.state}
				 errorTitle="Plaintiff history unavailable"
				 onRetry={() => void profileHook.refetch()}
				 ready={
					profileHook.data ? (
						<ProfileContent profile={profileHook.data} onStageSaved={onStageSaved} />
					) : (
						<StatusMessage tone="info">Select a call task to load plaintiff detail.</StatusMessage>
					)
				}
			/>
			{!selectedTask ? (
				<StatusMessage tone="info">Selecting a task also loads plaintiff history here.</StatusMessage>
			) : null}
		</section>
	);
}

type ProfileContentProps = {
	profile: OpsPlaintiffProfile;
	onStageSaved: () => void;
};

function ProfileContent({ profile, onStageSaved }: ProfileContentProps) {
	return (
		<div className="space-y-4">
			<div className="rounded-2xl border border-slate-200 bg-white p-4">
				<p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</p>
				<p className="text-lg font-semibold text-slate-900">{profile.summary.name}</p>
				<p className="text-sm text-slate-600">
					{profile.summary.firmName ?? 'No firm listed'} · Tier {profile.summary.tier ?? '—'} · {profile.summary.statusLabel}
				</p>
				<p className="text-sm text-slate-600">
					{profile.summary.phone ?? 'No phone'} · {profile.summary.email ?? 'No email'}
				</p>
			</div>

			<div className="space-y-2">
				<p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Contacts</p>
				{profile.contacts.length === 0 ? (
					<StatusMessage tone="info">No contacts on file.</StatusMessage>
				) : (
					<ul className="space-y-2 text-sm text-slate-700">
						{profile.contacts.map((contact) => (
							<li key={contact.id} className="rounded-xl border border-slate-200 px-3 py-2">
								<p className="font-semibold text-slate-900">{contact.name}</p>
								<p className="text-xs text-slate-500">{contact.role ?? 'No role provided'}</p>
								<p className="text-xs text-slate-500">{contact.phone ?? 'No phone'} · {contact.email ?? 'No email'}</p>
							</li>
						))}
					</ul>
				)}
			</div>

			<div className="space-y-2">
				<p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Contact history</p>
				{profile.callAttempts.length === 0 ? (
					<StatusMessage tone="info">No call attempts logged yet.</StatusMessage>
				) : (
					<ul className="space-y-2 text-sm text-slate-700">
						{profile.callAttempts.slice(0, 6).map((attempt) => (
							<li key={attempt.id} className="rounded-xl border border-slate-200 px-3 py-2">
								<p className="font-semibold text-slate-900">{attempt.outcome}</p>
								<p className="text-xs text-slate-500">{attempt.attemptedAt ? formatDateTime(attempt.attemptedAt) : '—'}</p>
								{attempt.notes ? <p className="text-xs text-slate-500">{attempt.notes}</p> : null}
							</li>
						))}
					</ul>
				)}
			</div>

			<div className="space-y-2">
				<p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Timeline</p>
				{profile.timeline.length === 0 ? (
					<StatusMessage tone="info">No events recorded.</StatusMessage>
				) : (
					<ul className="space-y-2">
						{profile.timeline.slice(0, 10).map((event) => (
							<li key={event.id} className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2 text-sm">
								<TimelineIcon type={event.type} />
								<div>
									<p className="font-semibold text-slate-900">{event.title}</p>
									<p className="text-xs text-slate-500">{event.occurredAt ? formatDateTime(event.occurredAt) : '—'}</p>
									{event.description ? <p className="text-xs text-slate-500">{event.description}</p> : null}
								</div>
							</li>
						))}
					</ul>
				)}
			</div>

			<div className="space-y-2">
				<p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Enforcement stage quick edit</p>
				<EnforcementStageEditor judgments={profile.judgments} onStageSaved={onStageSaved} />
			</div>
		</div>
	);
}

type EnforcementStageEditorProps = {
	judgments: OpsPlaintiffProfile['judgments'];
	onStageSaved: () => void;
};

function EnforcementStageEditor({ judgments, onStageSaved }: EnforcementStageEditorProps) {
	const [draft, setDraft] = useState<Record<string, string>>({});
	const [savingId, setSavingId] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		const initial: Record<string, string> = {};
		for (const judgment of judgments) {
			initial[judgment.judgmentId] = judgment.enforcementStage ?? 'pre_enforcement';
		}
		setDraft(initial);
	}, [judgments]);

	const handleSave = async (judgmentId: string) => {
		const selectedStage = draft[judgmentId];
		if (!selectedStage) {
			return;
		}
		setSavingId(judgmentId);
		setError(null);
		try {
			const numericId = Number(judgmentId);
			if (Number.isNaN(numericId)) {
				throw new Error('Judgment id is invalid.');
			}
			const { error: rpcError } = await supabaseClient.rpc('set_enforcement_stage', {
				_judgment_id: numericId,
				_new_stage: selectedStage,
			});
			if (rpcError) {
				throw rpcError;
			}
			await onStageSaved();
		} catch (err) {
			setError(err instanceof Error ? err.message : 'Unable to update enforcement stage.');
		} finally {
			setSavingId(null);
		}
	};

	if (judgments.length === 0) {
		return <StatusMessage tone="info">No judgments available for this plaintiff.</StatusMessage>;
	}

	return (
		<div className="space-y-3">
			{judgments.map((judgment) => (
				<div key={judgment.judgmentId} className="rounded-2xl border border-slate-200 bg-white p-3">
					<p className="text-sm font-semibold text-slate-900">Case {judgment.caseNumber ?? '—'}</p>
					<div className="mt-2 flex flex-col gap-2 md:flex-row md:items-center">
						<select
							className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
							value={draft[judgment.judgmentId] ?? judgment.enforcementStage ?? 'pre_enforcement'}
							onChange={(event) =>
								setDraft((prev) => ({
									...prev,
									[judgment.judgmentId]: event.target.value,
								}))
							}
						>
							{ENFORCEMENT_STAGE_OPTIONS.map((option) => (
								<option key={option.value} value={option.value}>
									{option.label}
								</option>
							))}
						</select>
						<button
							type="button"
							className="inline-flex items-center justify-center rounded-full bg-slate-900 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-sm transition hover:bg-slate-800 disabled:opacity-60"
							onClick={() => void handleSave(judgment.judgmentId)}
							disabled={savingId === judgment.judgmentId}
						>
							{savingId === judgment.judgmentId ? 'Saving…' : 'Save stage'}
						</button>
					</div>
					<p className="text-xs text-slate-500">Updated {formatDateTime(judgment.enforcementStageUpdatedAt)}</p>
				</div>
			))}
			{error ? <StatusMessage tone="warning">{error}</StatusMessage> : null}
		</div>
	);
}

type CallOutcomeDrawerProps = {
	isOpen: boolean;
	task: OpsCallTask | null;
	presetOutcome?: CallOutcomeValue;
	presetFollowUp?: string;
	isSubmitting: boolean;
	errorMessage: string | null;
	onClose: () => void;
	onSubmit: (payload: CallOutcomePayload) => Promise<void> | void;
};

function CallOutcomeDrawer({
	isOpen,
	task,
	presetOutcome,
	presetFollowUp,
	isSubmitting,
	errorMessage,
	onClose,
	onSubmit,
}: CallOutcomeDrawerProps) {
	const [outcome, setOutcome] = useState<CallOutcomeValue>('reached');
	const [interest, setInterest] = useState<InterestLevel>('hot');
	const [notes, setNotes] = useState('');
	const [followUp, setFollowUp] = useState('');

	useEffect(() => {
		if (!isOpen || !task) {
			return;
		}
		setOutcome(presetOutcome ?? 'reached');
		setInterest(presetOutcome && presetOutcome !== 'reached' ? 'none' : 'hot');
		setNotes(task.notes ?? '');
		setFollowUp(presetFollowUp ?? formatDatetimeLocal(task.dueAt));
	}, [isOpen, task, presetOutcome, presetFollowUp]);

	if (!isOpen || !task) {
		return null;
	}

	const interestDisabled = outcome !== 'reached';
	const followUpDisabled = outcome === 'do_not_call' || outcome === 'bad_number';

	return (
		<div className="fixed inset-0 z-40 flex items-stretch justify-end">
			<button
				type="button"
				className="h-full flex-1 bg-black/40"
				aria-label="Close call outcome drawer"
				onClick={onClose}
				disabled={isSubmitting}
			/>
			<div className="h-full w-full max-w-md overflow-y-auto bg-white p-6 shadow-2xl">
				<div className="flex items-start justify-between">
					<div>
						<p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Log Call Outcome</p>
						<h3 className="text-xl font-semibold text-slate-900">{task.plaintiffName}</h3>
						<p className="text-xs text-slate-500">Tier {task.tier ?? '—'} · {task.phone ?? 'No phone on file'}</p>
					</div>
					<button
						type="button"
						className="text-sm font-semibold text-slate-500 hover:text-slate-700"
						onClick={onClose}
						disabled={isSubmitting}
					>
						Close
					</button>
				</div>

				<form
					className="mt-6 space-y-4"
					onSubmit={(event) => {
						event.preventDefault();
						void onSubmit({ outcome, interest, notes, followUp });
					}}
				>
					<div>
						<label className="text-xs font-semibold uppercase tracking-widest text-slate-500">Outcome</label>
						<select
							className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
							value={outcome}
							onChange={(event) => {
								const next = event.target.value as CallOutcomeValue;
								setOutcome(next);
								if (next !== 'reached') {
									setInterest('none');
								} else if (interest === 'none') {
									setInterest('hot');
								}
								if (next === 'bad_number' || next === 'do_not_call') {
									setFollowUp('');
								}
							}}
							disabled={isSubmitting}
						>
							{CALL_OUTCOME_OPTIONS.map((option) => (
								<option key={option.value} value={option.value}>
									{option.label}
								</option>
							))}
						</select>
					</div>

					<div>
						<label className="text-xs font-semibold uppercase tracking-widest text-slate-500">Interest level</label>
						<select
							className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
							value={interest}
							onChange={(event) => setInterest(event.target.value as InterestLevel)}
							disabled={interestDisabled || isSubmitting}
						>
							{INTEREST_OPTIONS.map((option) => (
								<option key={option.value} value={option.value}>
									{option.label}
								</option>
							))}
						</select>
						{interestDisabled ? (
							<p className="mt-1 text-xs text-slate-500">Interest captured only when you reached them.</p>
						) : null}
					</div>

					<div>
						<label className="text-xs font-semibold uppercase tracking-widest text-slate-500">Notes</label>
						<textarea
							className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
							rows={4}
							placeholder="Who you spoke with, commitments, etc."
							value={notes}
							onChange={(event) => setNotes(event.target.value)}
							disabled={isSubmitting}
						/>
					</div>

					<div>
						<label className="text-xs font-semibold uppercase tracking-widest text-slate-500">Next follow-up</label>
						<input
							type="datetime-local"
							className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
							value={followUp}
							onChange={(event) => setFollowUp(event.target.value)}
							disabled={followUpDisabled || isSubmitting}
						/>
						{followUpDisabled ? (
							<p className="mt-1 text-xs text-slate-500">Follow-up disabled for Do Not Call / Wrong Number.</p>
						) : null}
					</div>

					{errorMessage ? (
						<p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{errorMessage}</p>
					) : null}

					<div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
						<button
							type="button"
							className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700"
							onClick={onClose}
							disabled={isSubmitting}
						>
							Cancel
						</button>
						<button
							type="submit"
							className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
							disabled={isSubmitting}
						>
							{isSubmitting ? 'Saving…' : 'Save outcome'}
						</button>
					</div>
				</form>
			</div>
		</div>
	);
}

type TimelineIconProps = {
	type: OpsTimelineEvent['type'];
};

type TimelineIconElement = ReturnType<typeof PhoneCall>;

function TimelineIcon({ type }: TimelineIconProps) {
	const iconMap: Record<OpsTimelineEvent['type'], TimelineIconElement> = {
		call: <PhoneCall className="h-4 w-4 text-blue-600" aria-hidden="true" />,
		status: <CircleAlert className="h-4 w-4 text-amber-600" aria-hidden="true" />,
		enforcement: <ActivitySquare className="h-4 w-4 text-emerald-600" aria-hidden="true" />,
	};
	return iconMap[type];
}

type TierBadgeProps = {
	tier: string | null;
};

function TierBadge({ tier }: TierBadgeProps) {
	if (!tier) {
		return <span className="rounded-full bg-slate-200 px-2 py-1 text-xs font-semibold text-slate-600">Unranked</span>;
	}
	const normalized = tier.trim().toUpperCase();
	const palette: Record<string, string> = {
		A: 'bg-emerald-100 text-emerald-800',
		B: 'bg-amber-100 text-amber-800',
		C: 'bg-slate-200 text-slate-600',
	};
	const className = palette[normalized] ?? 'bg-slate-200 text-slate-600';
	return (
		<span className={`rounded-full px-2 py-1 text-xs font-semibold uppercase tracking-wide ${className}`}>
			Tier {normalized}
		</span>
	);
}

type ToastProps = {
	message: string;
};

function Toast({ message }: ToastProps) {
	return (
		<div className="fixed right-6 top-24 z-30 rounded-full border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-700 shadow-sm">
			{message}
		</div>
	);
}

type OpsTimelineEvent = OpsPlaintiffProfile['timeline'][number];

function renderDue(value: string | null): string {
	return value ? formatDateTime(value) : '—';
}

function renderLastContact(value: string | null): string {
	return value ? formatDateTime(value) : 'Never';
}

function formatDatetimeLocal(value: string | null): string {
	if (!value) {
		return '';
	}
	const parsed = Date.parse(value);
	if (Number.isNaN(parsed)) {
		return '';
	}
	return new Date(parsed).toISOString().slice(0, 16);
}

function addDays(days: number): string {
	const now = new Date();
	now.setDate(now.getDate() + days);
	return now.toISOString();
}

function buildEmptySnapshot(): OpsConsoleSnapshot {
	return {
		tasks: [],
		nextBestTask: null,
		pipelineMetrics: [],
		dueToday: 0,
		overdue: 0,
	} satisfies OpsConsoleSnapshot;
}

