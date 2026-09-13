/**
 * RESOURCES - the facilities a coordinator can send people to, and how sure we are they are open.
 *
 * Two provenance rules shape this screen. A row's `availability` is a claim with a timestamp
 * attached: `availability_age` is shown next to it, because "available" from six days ago is not
 * the same sentence as "available" from an hour ago, and a coordinator who cannot see the age will
 * read it as now. And `contact_verified` is shown when it is false rather than hidden: an unverified
 * phone number that looks verified is how a team gets sent to a number nobody answers.
 *
 * Seeding is asynchronous on purpose. A nationwide Overpass query takes minutes, so the button
 * starts it and the screen reports the state the server is in; a spinner that outlives the request
 * would be a lie about progress.
 *
 * Retiring a facility never deletes it. If a wrong entry ever sent someone to a closed gate, the
 * audit trail has to show who listed it and who withdrew it.
 */

import { useState } from "react";

import { api } from "../../api/client";
import type { Availability, ResourceRow } from "../../api/types";
import { DemoChip, ProvenanceBadge } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import {
  DataTable,
  EnumSelect,
  FieldGrid,
  MetaStrip,
  RefreshRow,
  Screen,
  Stat,
  SubSection,
  TextFilter,
} from "../../components/rc/parts";
import { useAuth } from "../../auth/AuthContext";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { AVAILABILITY_KEYS, RESOURCE_TYPE_KEYS } from "../../i18n/strings";
import { serverLabel } from "../../utils/time";

/** `ResourceCreateIn.name` is `min_length=2`. */
const NAME_MIN = 2;

/** The form for adding a facility. Every field is one the schema accepts, and the two that can be
 *  wrong in a way the server cannot catch (a coordinate, a capacity) are optional. */
function emptyForm() {
  return {
    resource_type: "hospital",
    name: "",
    district: "",
    address: "",
    contact: "",
    capacity: "",
    availability: "unknown",
    latitude: "",
    longitude: "",
  };
}

export function ResourcesPage() {
  const { t, enumLabel, bcp47 } = useI18n();
  const { can } = useAuth();

  const [resourceType, setResourceType] = useState("");
  const [district, setDistrict] = useState("");
  const [availability, setAvailability] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);

  const state = useAsync(
    (signal) =>
      api.rc.resources(
        {
          resource_type: resourceType || undefined,
          district: district.trim() || undefined,
          availability: availability || undefined,
          include_inactive: includeInactive || undefined,
          limit: 300,
        },
        signal,
      ),
    [resourceType, district, availability, includeInactive],
  );
  const paused = usePolling(state.reload, 90_000);

  const [selected, setSelected] = useState<ResourceRow | null>(null);
  const [nextAvailability, setNextAvailability] = useState("unknown");
  const [nextCapacity, setNextCapacity] = useState("");
  const [contactVerified, setContactVerified] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(emptyForm);

  /** One place for "act, then re-read the list", so a successful write is never shown from a
   *  local copy of what was asked for. */
  const run = async (action: () => Promise<unknown>, clear: ResourceRow | null | undefined) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await action();
      await state.reload();
      setDone(true);
      if (clear !== undefined) setSelected(clear);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const pick = (row: ResourceRow) => {
    setSelected(row);
    setNextAvailability(row.availability || "unknown");
    setNextCapacity(row.capacity === null ? "" : String(row.capacity));
    setContactVerified(row.contact_verified);
    setReason("");
    setDone(false);
    setError(null);
  };

  const set = (key: keyof ReturnType<typeof emptyForm>) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const canWrite = can("resources:update");

  return (
    <Screen title={t("nav_resources")} intro={t("resources_intro")}>
      <RefreshRow onRefresh={state.reload} seconds={90} paused={paused} />

      <section className="card">
        <div className="filter-grid">
          <EnumSelect
            label={t("col_type")}
            keys={RESOURCE_TYPE_KEYS}
            value={resourceType}
            onChange={setResourceType}
          />
          <EnumSelect
            label={t("availability")}
            keys={AVAILABILITY_KEYS}
            value={availability}
            onChange={setAvailability}
          />
          <TextFilter label={t("filter_district")} value={district} onChange={setDistrict} />
        </div>
        <div className="row">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(event) => setIncludeInactive(event.target.checked)}
            />
            <span>{t("show_archived")}</span>
          </label>
          {canWrite ? (
            <button type="button" className="button small" onClick={() => setShowAdd((open) => !open)}>
              {t("add_resource")}
            </button>
          ) : null}
        </div>
      </section>

      <Panel state={state} isEmpty={(data) => data.items.length === 0} emptyTitle={t("bucket_empty")}>
        {(data) => (
          <>
            <SubSection title={t("resource_catalogue")} count={data.catalogue.total}>
              <div className="stat-grid">
                <Stat
                  label={t("total")}
                  value={data.catalogue.total}
                  note={
                    data.catalogue.last_change
                      ? `${t("last_change")}: ${serverLabel(data.catalogue.last_change, data.catalogue.last_change_age, bcp47) ?? "—"}`
                      : null
                  }
                />
                {Object.keys(AVAILABILITY_KEYS).map((key) => (
                  <Stat
                    key={key}
                    label={enumLabel(AVAILABILITY_KEYS, key)}
                    value={data.catalogue.by_availability[key] ?? 0}
                  />
                ))}
              </div>
              {data.empty_reason ? (
                <p className="meta">
                  {t("catalogue_empty_reason")}: {data.empty_reason}
                </p>
              ) : null}
            </SubSection>

            <section className="card">
              <MetaStrip
                generatedAt={null}
                extra={t("showing_of", { shown: data.items.length, total: data.count })}
              />
              <DataTable
                columns={[
                  {
                    id: "name",
                    label: t("resource_name"),
                    cell: (row: ResourceRow) => (
                      <div className="stack-sm">
                        <span className="row">
                          {row.demo ? <DemoChip /> : null}
                          <strong>{row.name}</strong>
                        </span>
                        <span className="meta">{row.address ?? "—"}</span>
                      </div>
                    ),
                  },
                  {
                    id: "type",
                    label: t("col_type"),
                    cell: (row: ResourceRow) => enumLabel(RESOURCE_TYPE_KEYS, row.resource_type),
                  },
                  { id: "district", label: t("col_district"), cell: (row: ResourceRow) => row.district ?? "—" },
                  {
                    id: "availability",
                    label: t("availability"),
                    cell: (row: ResourceRow) => (
                      <div className="stack-sm">
                        <span className="chip provenance">
                          {enumLabel(AVAILABILITY_KEYS, row.availability)}
                        </span>
                        {/* The age of the claim, always: "available" is only true as of a moment. */}
                        <span className="meta">
                          {row.availability_age
                            ? `${t("last_verified")}: ${row.availability_age}`
                            : t("last_verified") + ": —"}
                        </span>
                      </div>
                    ),
                  },
                  {
                    id: "capacity",
                    label: t("capacity"),
                    numeric: true,
                    cell: (row: ResourceRow) => (row.capacity === null ? "—" : row.capacity),
                  },
                  {
                    id: "contact",
                    label: t("contact"),
                    cell: (row: ResourceRow) => (
                      <div className="stack-sm">
                        <span className="mono">{row.contact ?? "—"}</span>
                        {row.contact ? (
                          <span className="meta">
                            {row.contact_verified ? t("verified_by_operator") : t("contact_unverified")}
                          </span>
                        ) : null}
                      </div>
                    ),
                  },
                  {
                    id: "source",
                    label: t("source"),
                    cell: (row: ResourceRow) => (
                      <div className="stack-sm">
                        <ProvenanceBadge value={row.provenance} />
                        {row.source_url ? (
                          <a className="meta" href={row.source_url} target="_blank" rel="noreferrer noopener">
                            {t("open_source")} ↗
                          </a>
                        ) : (
                          <span className="meta">{row.source ?? "—"}</span>
                        )}
                        {row.has_location ? null : <span className="meta">{t("not_on_map")}</span>}
                      </div>
                    ),
                  },
                  {
                    id: "open",
                    label: t("col_action"),
                    cell: (row: ResourceRow) =>
                      canWrite ? (
                        <button
                          type="button"
                          className="button small"
                          disabled={busy}
                          onClick={() => pick(row)}
                        >
                          {t("take_action")}
                        </button>
                      ) : (
                        <span className="meta">—</span>
                      ),
                  },
                ]}
                rows={data.items}
                keyOf={(row) => row.id}
              />
            </section>

            <SubSection title={t("seed_state")} note={t("resources_intro")}>
              <FieldGrid
                items={[
                  { label: t("status"), value: data.seed.state_label || data.seed.state },
                  {
                    label: t("generated_at"),
                    value: data.seed.finished_at
                      ? (serverLabel(data.seed.finished_at, null, bcp47) ?? data.seed.finished_at)
                      : data.seed.started_at
                        ? t("seed_running")
                        : null,
                    when: Boolean(data.seed.started_at || data.seed.finished_at),
                  },
                ]}
              />
              {data.seed.result ? (
                <p className="meta mono">
                  {t("seed_result")}: {JSON.stringify(data.seed.result)}
                </p>
              ) : null}
              {canWrite ? (
                <button
                  type="button"
                  className="button"
                  disabled={busy}
                  // An empty `types` list means every kind the catalogue knows, which is what an
                  // operator clicking "seed" expects.
                  onClick={() => void run(() => api.rc.seedResources({}), undefined)}
                >
                  {busy ? t("sending") : t("seed_run")}
                </button>
              ) : null}
            </SubSection>

            {selected ? (
              <SubSection title={selected.name} note={t("actions_hint")}>
                <div className="action-form">
                  <EnumSelect
                    label={t("availability")}
                    keys={AVAILABILITY_KEYS}
                    value={nextAvailability}
                    onChange={setNextAvailability}
                    includeAll={false}
                  />
                  <div className="field">
                    <label htmlFor="res-capacity">{t("capacity")}</label>
                    <input
                      id="res-capacity"
                      type="number"
                      min={0}
                      max={1_000_000}
                      value={nextCapacity}
                      onChange={(event) => setNextCapacity(event.target.value)}
                    />
                  </div>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={contactVerified}
                      onChange={(event) => setContactVerified(event.target.checked)}
                    />
                    <span>{t("verified_by_operator")}</span>
                  </label>
                  <div className="field">
                    <label htmlFor="res-reason">{t("reason")}</label>
                    <input
                      id="res-reason"
                      type="text"
                      maxLength={500}
                      value={reason}
                      placeholder={t("deactivate_hint")}
                      onChange={(event) => setReason(event.target.value)}
                    />
                  </div>
                  <div className="row">
                    <button
                      type="button"
                      className="button primary"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () =>
                            api.rc.resourceAvailability(selected.id, {
                              availability: nextAvailability as Availability,
                              capacity: nextCapacity === "" ? null : Number(nextCapacity),
                              contact_verified: contactVerified,
                              reason: reason.trim().slice(0, 500),
                            }),
                          null,
                        )
                      }
                    >
                      {busy ? t("sending") : t("update_availability")}
                    </button>
                    <button
                      type="button"
                      className="button danger"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () => api.rc.deactivateResource(selected.id, { reason: reason.trim().slice(0, 500) }),
                          null,
                        )
                      }
                    >
                      {t("deactivate_resource")}
                    </button>
                    <button type="button" className="button ghost" onClick={() => setSelected(null)}>
                      {t("close")}
                    </button>
                  </div>
                  {error ? (
                    <p className="field-hint breach" role="alert">
                      {error}
                    </p>
                  ) : null}
                  {done ? <p className="field-hint" role="status">{t("action_done")}</p> : null}
                </div>
              </SubSection>
            ) : null}

            {showAdd && canWrite ? (
              <SubSection title={t("add_resource")} note={t("deactivate_hint")}>
                <div className="action-form">
                  <EnumSelect
                    label={t("col_type")}
                    keys={RESOURCE_TYPE_KEYS}
                    value={form.resource_type}
                    onChange={(next) => setForm((current) => ({ ...current, resource_type: next }))}
                    includeAll={false}
                  />
                  <EnumSelect
                    label={t("availability")}
                    keys={AVAILABILITY_KEYS}
                    value={form.availability}
                    onChange={(next) => setForm((current) => ({ ...current, availability: next }))}
                    includeAll={false}
                  />
                  <div className="filter-grid">
                    <div className="field">
                      <label htmlFor="res-name">{t("resource_name")}</label>
                      <input
                        id="res-name"
                        type="text"
                        maxLength={256}
                        value={form.name}
                        onChange={set("name")}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="res-district">{t("district")}</label>
                      <input
                        id="res-district"
                        type="text"
                        maxLength={64}
                        value={form.district}
                        onChange={set("district")}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="res-address">{t("resource_address")}</label>
                      <input
                        id="res-address"
                        type="text"
                        maxLength={256}
                        value={form.address}
                        onChange={set("address")}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="res-contact">{t("contact")}</label>
                      <input
                        id="res-contact"
                        type="text"
                        maxLength={64}
                        value={form.contact}
                        onChange={set("contact")}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="res-capacity-new">{t("capacity")}</label>
                      <input
                        id="res-capacity-new"
                        type="number"
                        min={0}
                        max={1_000_000}
                        value={form.capacity}
                        onChange={set("capacity")}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="res-lat">{t("location")}</label>
                      <input
                        id="res-lat"
                        type="number"
                        step="any"
                        placeholder="latitude"
                        value={form.latitude}
                        onChange={set("latitude")}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="res-lng" className="sr-only">
                        {t("location")}
                      </label>
                      <input
                        id="res-lng"
                        type="number"
                        step="any"
                        placeholder="longitude"
                        value={form.longitude}
                        onChange={set("longitude")}
                      />
                    </div>
                  </div>
                  <div className="row">
                    <button
                      type="button"
                      className="button primary"
                      disabled={busy || form.name.trim().length < NAME_MIN}
                      onClick={() =>
                        void run(
                          () =>
                            api.rc.addResource({
                              resource_type: form.resource_type,
                              name: form.name.trim(),
                              district: form.district.trim() || null,
                              address: form.address.trim() || null,
                              contact: form.contact.trim() || null,
                              capacity: form.capacity === "" ? null : Number(form.capacity),
                              availability: form.availability as Availability,
                              // A blank coordinate is no coordinate: sending 0 would place the
                              // facility in the Gulf of Guinea and the map would draw it there.
                              latitude: form.latitude === "" ? null : Number(form.latitude),
                              longitude: form.longitude === "" ? null : Number(form.longitude),
                            }),
                          undefined,
                        )
                      }
                    >
                      {busy ? t("sending") : t("save")}
                    </button>
                    <button type="button" className="button ghost" onClick={() => setShowAdd(false)}>
                      {t("close")}
                    </button>
                  </div>
                </div>
              </SubSection>
            ) : null}
          </>
        )}
      </Panel>
    </Screen>
  );
}
