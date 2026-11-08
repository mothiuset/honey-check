import { DataTable, Lede, Notice } from '@/presentation/shared/components'
import { DeviceFilters } from '../../components/DeviceFilters/DeviceFilters'
import { DevicePager } from '../../components/DevicePager/DevicePager'
import { VersionsPanel } from '../../components/VersionsPanel/VersionsPanel'
import { deviceColumns } from '../../formatters/deviceColumns'
import { facetFilters } from '../../formatters/deviceFacets'
import { useDevices } from '../../hooks/useDevices'

export function DevicesPage() {
  const devices = useDevices()
  const { page, query } = devices
  return (
    <>
      <h1>Equipos y versiones</h1>
      <Lede>
        Inventarios guardados en esta carpeta, agrupados por equipo. Cada
        análisis es una versión nueva.
      </Lede>
      <DeviceFilters
        text={devices.text}
        query={query}
        filters={facetFilters(page)}
        onSearch={devices.search}
        onFilter={devices.filter}
      />
      {devices.notice ? (
        <Notice>
          <p>{devices.notice}</p>
        </Notice>
      ) : null}
      <Lede live>
        {page
          ? `${String(page.total)} ${page.total === 1 ? 'equipo' : 'equipos'}`
          : ''}
      </Lede>
      <DataTable
        id="device-results"
        columns={deviceColumns}
        rows={page?.items ?? []}
        rowKey={(device) => device.deviceKey}
        loading={devices.loading}
        serverSort={{
          key: query.sort,
          order: query.order,
          onSort: devices.sort,
        }}
        renderExpanded={(device) => <VersionsPanel device={device} />}
        emptyText={
          devices.hasFilters
            ? 'Ningún equipo coincide con la búsqueda o los filtros.'
            : 'Todavía no hay inventarios en esta carpeta.'
        }
      />
      {page && page.pages > 1 ? (
        <DevicePager
          page={page}
          size={query.size}
          onPage={devices.goToPage}
          onSize={devices.setPageSize}
        />
      ) : null}
    </>
  )
}
