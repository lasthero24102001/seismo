import { ArrowDown, ArrowUp, TriangleAlert } from "lucide-react";
import { fmtDate, fmtNum, fmtTime } from "@/lib/format";
import type { SeismicEvent } from "@/lib/api";
import { Table, TBody, TD, TH, THead, TR } from "./ui/table";

interface Props {
  events: SeismicEvent[];
  sort?: string; order?: "asc" | "desc"; onSort?: (key: string) => void;
  onRowClick?: (e: SeismicEvent) => void; hideStation?: boolean;
}

const COLS: { key: string; label: string; sort?: string; align?: "right" }[] = [
  { key: "station", label: "Станция", sort: "station" },
  { key: "date", label: "Дата", sort: "date" },
  { key: "p", label: "P волна", sort: "p_time" },
  { key: "s", label: "S волна", sort: "s_time" },
  { key: "o", label: "Время в очаге", sort: "origin_time" },
  { key: "sp", label: "S-P", sort: "s_minus_p", align: "right" },
  { key: "r", label: "R км", sort: "r_km", align: "right" },
  { key: "ap", label: "A(P)", sort: "amp_p", align: "right" },
  { key: "as", label: "A(S)", sort: "amp_s", align: "right" },
  { key: "mb", label: "Mb", sort: "mb", align: "right" },
  { key: "ml", label: "ML", sort: "ml", align: "right" },
  { key: "vp", label: "Ep Vp", sort: "ep_vp", align: "right" },
  { key: "vs", label: "Ep Vs", sort: "ep_vs", align: "right" },
  { key: "vv", label: "Ep Vp/Vs", sort: "ep_vp_vs", align: "right" },
];

export function EventsTable({ events, sort, order, onSort, onRowClick, hideStation }: Props) {
  const cols = hideStation ? COLS.filter((c) => c.key !== "station") : COLS;
  return (
    <Table>
      <THead>
        <TR className="hover:bg-slate-100">
          <TH className="w-6 px-2" />
          {cols.map((c) => (
            <TH key={c.key} className={c.align === "right" ? "text-right" : ""}>
              {onSort && c.sort ? (
                <button className="inline-flex items-center gap-1 hover:text-primary" onClick={() => onSort(c.sort!)}>
                  {c.label}
                  {sort === c.sort && (order === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                </button>
              ) : c.label}
            </TH>
          ))}
        </TR>
      </THead>
      <TBody>
        {events.map((e) => (
          <TR key={e.id} onClick={() => onRowClick?.(e)} className={`${onRowClick ? "cursor-pointer" : ""} ${e.needs_review ? "bg-amber-50/60" : ""}`}>
            <TD className="px-2">{e.needs_review && <TriangleAlert className="h-3.5 w-3.5 text-amber-600" aria-label="Требует проверки" />}</TD>
            {!hideStation && <TD className="font-medium">{e.station_code}</TD>}
            <TD>{fmtDate(e.event_date)}</TD>
            <TD>{e.p_phase} {fmtTime(e.p_time)}</TD>
            <TD>{e.s_phase} {fmtTime(e.s_time)}</TD>
            <TD>{fmtTime(e.origin_time)}</TD>
            <TD className="text-right">{fmtNum(e.s_minus_p, 2)}</TD>
            <TD className="text-right">{fmtNum(e.r_km, 1)}</TD>
            <TD className="text-right">{fmtNum(e.amp_p, 2)}</TD>
            <TD className="text-right">{fmtNum(e.amp_s, 2)}</TD>
            <TD className="text-right font-medium">{fmtNum(e.mb, 1)}</TD>
            <TD className="text-right font-medium">{fmtNum(e.ml, 1)}</TD>
            <TD className="text-right">{fmtNum(e.ep_vp, 2)}</TD>
            <TD className="text-right">{fmtNum(e.ep_vs, 2)}</TD>
            <TD className="text-right">{fmtNum(e.ep_vp_vs, 2)}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
