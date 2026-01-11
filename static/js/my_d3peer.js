"use strict";

function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    return { ips: params.get('ips') };
}

function filterTable(tableId, selectedValue) {
    const table = document.getElementById(tableId);
    const rows = table.getElementsByTagName('tr');
    for (let i = 1; i < rows.length; i++) {
        const cells = rows[i].getElementsByTagName('td');
        const match = cells[1].innerText === selectedValue || selectedValue === 'Show All';
        rows[i].style.display = match ? '' : 'none';
    }
}

function createTable(id, headers) {
    const table = document.createElement('table');
    table.id = id;
    const headerRow = headers.map(header => `<th>${header}</th>`).join('');
    table.innerHTML = `<thead><tr>${headerRow}</tr></thead><tbody></tbody>`;
    return table;
}

function createTableRow(cells, rowColor = "") {
    const row = document.createElement('tr');
    if (rowColor) {
        row.style.backgroundColor = rowColor;
    }
    cells.forEach(cell => {
        const cellElement = document.createElement('td');
        cellElement.textContent = cell;
        row.appendChild(cellElement);
    });
    return row;
}

function createDropdown(selector, options) {
    const dropdown = d3.select(selector);
    dropdown.selectAll('option')
        .data(['Show All', ...options])
        .join('option')
        .text(d => d)
        .attr('value', d => d);
}

// function createSimulation(nodes, links, width, height, radius, svgGroup, data) {
//     return d3.forceSimulation(nodes)
//         .force("link", d3.forceLink(links).id(d => d.id).distance(150))
//         .force("charge", d3.forceManyBody().strength(-300))
//         .force("center", d3.forceCenter(width / 2.3, height / 2.8))
//         .on('tick', () => {
//             svgGroup.selectAll('line')
//                 .data(links)
//                 .join('line')
//                 .attr('stroke', '#999')
//                 .attr('stroke-width', 1.5)
//                 .attr('x1', d => d.source.x || 0)
//                 .attr('y1', d => d.source.y || 0)
//                 .attr('x2', d => d.target.x || 0)
//                 .attr('y2', d => d.target.y || 0);

//             svgGroup.selectAll('circle')
//                 .data(nodes)
//                 .join('circle')
//                 .attr('r', radius)
//                 .attr('fill', d => d.type === 'router' ? 'blue' : 'green')
//                 .attr('cx', d => d.x || 0)
//                 .attr('cy', d => d.y || 0)
//                 .call(d3.drag().on('start', dragStart).on('drag', dragging).on('end', dragEnd));

//             svgGroup.selectAll('text')
//                 .data(nodes)
//                 .join('text')
//                 .attr('font-size', 10)
//                 .attr('x', d => (d.x || 0) + 12)
//                 .attr('y', d => (d.y || 0) + 5)
//                 .style('text-anchor', 'start')
//                 .each(function (d) {
//                     const textElement = d3.select(this);
//                     textElement.selectAll('tspan').remove();
//                     textElement.append('tspan').attr('x', d.x + 12).attr('dy', '0em')
//                         .text(d.type === 'router' ? `${data.hostname || ''} ${d.id}` : `${data.peer_NodeName || ''} ${d.id}`);
//                     // textElement.append('tspan').attr('x', d.x + 12).attr('dy', '1.2em')
//                     //     .text(d.type === 'router' ? `Local AS: ${d.localAS}` : `Remote AS: ${d.remoteAS}`);
//                 });
//         });
// }

function displayTables(data) {
    const container = document.getElementById('table-container');
    displayBgpTable(data.BGP, container, data);
    displayOspfTable(data.OSPF, container, data);
}

function displayBgpTable(BGP, container, data) {
    if (!Array.isArray(BGP) || BGP.length === 0) {
        console.error("BGP is not an array or is empty. Value of BGP:", BGP);
        document.getElementById("hostInfo").innerHTML += `<p>BGP info not found, not supported or configured.</p>`;
        document.getElementById("bgpDiv").remove();
        return;
    }

    const bgpTable = createTable("bgpPeerTable", [
        "Host Info", "VPN Instance", "Local RouterID", "Local AS", "Peer IP", "Peer Node", "Peer AS", "Peer Uptime", "Peer Status"
    ]);

    const tbody = bgpTable.querySelector('tbody');
    const hostColors = new Map();
    const colors = ['', '#d3d3d3'];

    BGP.forEach(instance => {
        if (Array.isArray(instance.Peer)) {
            instance.Peer.forEach(peer => {
                // const hostInfo = `${instance.hostname} (${instance.host_ip})`;
                const hostInfo = `${instance.hostname}`;
                if (!hostColors.has(hostInfo)) {
                    hostColors.set(hostInfo, colors[hostColors.size % colors.length]);
                }
                const rowColor = hostColors.get(hostInfo);

                // Find the peer node name based on the peer IP matching the local router ID of other instances
                // let peer_NodeName = "na";
                BGP.forEach(otherInstance => {
                    if (otherInstance.local_router_id === peer.peer_IP) {
                        // peerNode = `${otherInstance.hostname} (${otherInstance.host_ip})`;
                        peer.peer_NodeName = `${otherInstance.hostname}`;
                    }
                });

                // console.log(peerNodeIndex, peerNode, data.host_ip, data.hostname);

                const row = createTableRow([
                    hostInfo, instance.VPN_instance, instance.local_router_id, instance.local_as_number,
                    peer.peer_IP, peer.peer_NodeName, peer.peer_AS, peer.peer_uptime, peer.peer_status
                ], rowColor);
                tbody.appendChild(row);
            });
        } else {
            console.warn("No peers found for instance:", instance);
        }
    });

    container.appendChild(bgpTable);
    renderBgpVisualization(data);
}

function displayOspfTable(OSPF, container, data) {
    if (!Array.isArray(OSPF) || OSPF.length === 0) {
        console.error("OSPF is not an array or is empty. Value of OSPF:", OSPF);
        document.getElementById("hostInfo").innerHTML += `<p>OSPF info not found, not supported or configured.</p>`;
        document.getElementById("ospfDiv").remove();
        return;
    }

    const ospfTable = createTable("ospfPeerTable", [
        "Host Info", "Process", "Process Router ID", "Area", "Neighbor Router ID", "Neighbor Name", "Neighbor Address", "Neighbor State", "Neighbor Interface"
    ]);

    const tbody = ospfTable.querySelector('tbody');
    const hostColors = new Map();
    const colors = ['', '#d3d3d3'];

    OSPF.forEach(process => {
        const { process: processId, "process router ID": routerId, area_info: areas } = process;
        areas.forEach(area => {
            const { Area, neighbor_info: neighbors } = area;
            neighbors.forEach(neighbor => {
                const hostInfo = `${process.hostname}`;
                const neighborId = `${neighbor["Router ID"]}`;
                if (!hostColors.has(hostInfo)) {
                    hostColors.set(hostInfo, colors[hostColors.size % colors.length]);
                }
                const rowColor = hostColors.get(hostInfo);

                // Find the neighbor node name based on the neighbor IP matching the router ID of other processes
                let neighborName = "na";
                OSPF.forEach(otherProcess => {
                    if (otherProcess["process router ID"] === neighborId) {
                        neighborName = `${otherProcess.hostname}`;
                    }
                });
                // console.log("process:",process);

                const row = createTableRow([
                    hostInfo, processId, routerId, Area, neighbor["Router ID"],
                    neighborName, neighbor.Address, neighbor.State, neighbor.Interface
                ], rowColor);
                tbody.appendChild(row);
            });
        });
    });

    container.appendChild(ospfTable);
    renderOspfVisualization(data);
}

function filterTable(tableId, selectedValue) {
    const table = document.getElementById(tableId);
    const rows = table.getElementsByTagName('tr');
    for (let i = 1; i < rows.length; i++) {
        const cells = rows[i].getElementsByTagName('td');
        const match = cells[1].innerText === selectedValue || selectedValue === 'Show All';
        rows[i].style.display = match ? '' : 'none';
    }
}

function renderBgpVisualization(data) {
    const svg = d3.select('#bgp-visualization')
        .attr("preserveAspectRatio", "xMidYMid meet")
        .call(d3.zoom().scaleExtent([0.5, 5]).on("zoom", (event) => svgGroup.attr("transform", event.transform)));

    const svgGroup = svg.append("g");
    const width = +svg.attr('width');
    const height = +svg.attr('height');
    const radius = 10;

    const vpnInstances = prepareBgpData(data.BGP);
    createDropdown('#vpn-dropdown', vpnInstances.keys());

    function updateVisualization(selectedVPN) {
        const group = vpnInstances.get(selectedVPN);
        if (!group) {
            console.warn(`No data found for VPN instance: ${selectedVPN}`);
            return;
        }
        // Create a zoom behavior to enable scaling and panning
        const zoom = d3.zoom()
                .scaleExtent([0.5, 5]) // Set min and max zoom levels
                .on('zoom', (event) => {
                    svgGroup.attr('transform', event.transform);
                });
            // Apply zoom to the SVG
        svg.call(zoom);                
        svg.selectAll('g').remove();
        const svgGroup = svg.append('g');
        const simulation = createSimulation(group.nodes, group.links, width, height, radius, svgGroup, data);
        simulation.alpha(1).restart();
    }

    const initialVPN = [...vpnInstances.keys()][0];
    updateVisualization(initialVPN);
    d3.select('#vpn-dropdown').on('change', function () {
        const selectedVPN = this.value;
        svg.selectAll('*').remove();
        updateVisualization(selectedVPN);
    });
}

function prepareBgpData(BGP) {
    const vpnInstances = new Map();
    const asColors = new Map();
    const colors = d3.schemeCategory10;

    BGP.forEach(instance => {
        const vpnInstance = instance.VPN_instance || "Global";
        const localAs = instance.local_as_number;
        if (!vpnInstances.has(vpnInstance)) {
            vpnInstances.set(vpnInstance, { nodes: [], links: [] });
        }
        const group = vpnInstances.get(vpnInstance);

        // Assign colors to AS numbers
        if (!asColors.has(localAs)) {
            asColors.set(localAs, colors[asColors.size % colors.length]);
        }
        const nodeColor = asColors.get(localAs);

        // Add the local router node
        group.nodes.push({ id: instance.local_router_id, type: 'router', vpn: vpnInstance, localAS: localAs, color: nodeColor, hostInfo: `${instance.hostname}` });

        // Add peer nodes and links
        instance.Peer.forEach(peer => {
            if (!asColors.has(peer.peer_AS)) {
                asColors.set(peer.peer_AS, colors[asColors.size % colors.length]);
            }
            const peerColor = asColors.get(peer.peer_AS);
            
            // console.log('instance:', instance  );
            group.nodes.push({ id: peer.peer_IP, type: 'peer', vpn: vpnInstance, remoteAS: peer.peer_AS, color: peerColor, hostInfo: `${peer.peer_NodeName}` });
            group.links.push({ source: instance.local_router_id, target: peer.peer_IP, vpn: vpnInstance, localAS: localAs, remoteAS: peer.peer_AS });

        });
    });

    // Remove duplicate nodes
    vpnInstances.forEach(group => {
        const uniqueNodes = new Map();
        group.nodes.forEach(node => {
            if (!uniqueNodes.has(node.id)) {
                uniqueNodes.set(node.id, node);
            }
        });
        group.nodes = Array.from(uniqueNodes.values());
    });

    return vpnInstances;
}

function createDropdown(selector, options) {
    const dropdown = d3.select(selector);
    dropdown.selectAll('option')
        .data(['Show All', ...options])
        .join('option')
        .text(d => d)
        .attr('value', d => d);
}

function createSimulation(nodes, links, width, height, radius, svgGroup, data) {
    console.log("createSimulation nodes:", nodes);
    return d3.forceSimulation(nodes)
        .force("link", d3.forceLink(links).id(d => d.id).distance(150))
        .force("charge", d3.forceManyBody().strength(-300))
        .force("center", d3.forceCenter(width / 2.3, height / 2.8))
        .on('tick', () => {
            svgGroup.selectAll('line')
                .data(links)
                .join('line')
                .attr('stroke', '#999')
                .attr('stroke-width', 1.5)
                .attr('x1', d => d.source.x || 0)
                .attr('y1', d => d.source.y || 0)
                .attr('x2', d => d.target.x || 0)
                .attr('y2', d => d.target.y || 0);

                svgGroup.selectAll('circle')
                .data(nodes)
                .join('circle')
                .attr('r', radius)
                .attr('fill', d => d.color)
                .attr('cx', d => d.x || 0)
                .attr('cy', d => d.y || 0)
                .call(d3.drag().on('start', dragStart).on('drag', dragging).on('end', dragEnd));

                svgGroup.selectAll('text')
                .data(nodes)
                .join('text')
                .attr('font-size', 10)
                .attr('x', d => (d.x || 0) + 12)
                .attr('y', d => (d.y || 0) + 5)
                .style('text-anchor', 'start')
                .each(function (d) {
                    const textElement = d3.select(this);
                    textElement.selectAll('tspan').remove();
                    textElement.append('tspan').attr('x', d.x + 12).attr('dy', '0em')
                        .text(d.hostInfo);

                    // Only add for BGP nodes
                    if (d.vpn) {
                        textElement.append('tspan').attr('x', d.x + 12).attr('dy', '1.2em')
                            .text(`Router ID: ${d.id}`);
                        textElement.append('tspan').attr('x', d.x + 12).attr('dy', '1.2em')
                            .text(`AS: ${d.localAS || d.remoteAS}`);
                    }

                    // Only add for OSPF nodes
                    if (d.processId) {
                        textElement.append('tspan').attr('x', d.x + 12).attr('dy', '1.2em')
                            .text(`Router ID: ${d.id}`);
                        // textElement.append('tspan').attr('x', d.x + 12).attr('dy', '1.2em')
                        //     .text(`AS: ${d.localAS || d.remoteAS}`);
                    }                    
                });
        });
}

function renderOspfVisualization(data) {
    const svg = d3.select('#ospf-visualization')
        .attr("preserveAspectRatio", "xMidYMid meet")
        .call(d3.zoom().scaleExtent([0.5, 5]).on("zoom", (event) => svgGroup.attr("transform", event.transform)));

    const svgGroup = svg.append("g");
    const width = +svg.attr('width');
    const height = +svg.attr('height');
    const radius = 10;

    const ospfProcesses = prepareOspfData(data.OSPF);
    createDropdown('#ospf-dropdown', ospfProcesses.keys());

    function updateVisualization(selectedProcess) {
        const group = ospfProcesses.get(selectedProcess);
        if (!group) {
            console.warn(`No data found for OSPF process: ${selectedProcess}`);
            return;
        }

        // Create a zoom behavior to enable scaling and panning
        const zoom = d3.zoom()
                .scaleExtent([0.5, 5]) // Set min and max zoom levels
                .on('zoom', (event) => {
                    svgGroup.attr('transform', event.transform);
                });
            // Apply zoom to the SVG
        svg.call(zoom);                

        svg.selectAll('g').remove();
        const svgGroup = svg.append('g');
        const simulation = createSimulation(group.nodes, group.links, width, height, radius, svgGroup, data);
        simulation.alpha(1).restart();
    }

    const initialProcess = [...ospfProcesses.keys()][0];
    updateVisualization(initialProcess);
    d3.select('#ospf-dropdown').on('change', function () {
        const selectedProcess = this.value;
        svg.selectAll('*').remove();
        updateVisualization(selectedProcess);
    });
}

function prepareOspfData(OSPF) {
    const ospfProcesses = new Map();
    const Colors = new Map();
    const colors = d3.schemeCategory10;    
    
    OSPF.forEach(process => {
        const processId = process.process;
        const routerId = process["process router ID"];
        if (!ospfProcesses.has(processId)) {
            ospfProcesses.set(processId, { nodes: new Map(), links: [] });
        }
        const group = ospfProcesses.get(processId);

        // Add the local router node if not already present
        if (!group.nodes.has(routerId)) {
            group.nodes.set(routerId, { id: routerId, type: 'router', processId, hostInfo: `${process.hostname}` });
        }
        // Add neighbor nodes and links
        process.area_info.forEach(area => {
            area.neighbor_info.forEach(neighbor => {
                // console.log("neighbor:", neighbor);
                if (!Colors.has(neighbor["Router ID"])) {
                    Colors.set(neighbor["Router ID"], colors[Colors.size % colors.length]);
                }
                const neighborColor = Colors.get(neighbor["Router ID"]);

                // Find the neighbor node name based on the neighbor IP matching the router ID of other processes
                let neighborName = "na";
                OSPF.forEach(otherProcess => {
                    if (otherProcess["process router ID"] === neighbor["Router ID"]) {
                        neighborName = `${otherProcess.hostname}`;
                    }
                });                

                // Add the neighbor node if not already present
                if (!group.nodes.has(neighbor["Router ID"])) {
                    group.nodes.set(neighbor["Router ID"], { id: neighbor["Router ID"], type: 'peer', processId, color: neighborColor, hostInfo: neighborName });
                }

                group.links.push({ source: routerId, target: neighbor["Router ID"], processId });
            });
        });

    });

    // Convert nodes map to array
    ospfProcesses.forEach(group => {
        group.nodes = Array.from(group.nodes.values());
    });
        
    return ospfProcesses;
}

function dragStart(event, d) {
    if (!event.active) d3.forceSimulation().alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;
}

function dragging(event, d) {
    d.fx = event.x;
    d.fy = event.y;
}

function dragEnd(event, d) {
    if (!event.active) d3.forceSimulation().alphaTarget(0);
    d.fx = null;
    d.fy = null;
}

console.log("my_d3peer.js loaded success.");
