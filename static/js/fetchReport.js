// JavaScript source code

// Function to extract all IP addresses from log entries
function getAllIPs(logEntries) {
    const ips = [];
    logEntries.forEach(entry => {
        ips.push(entry.ip);
    });
    return ips;
}

async function fetchReport(url, outputDiv) {
    try {
        // cleanup 
        document.getElementById('output').innerHTML = '';
        document.getElementById('logTableBody').innerHTML = '';

        const response = await fetch(url); // Fetch the file
        if (!response.ok) {
            throw new Error('Failed to fetch file');
        }
        const text = await response.text(); // Get the text content
        const lines = text.split('\n'); // Split text into lines

        document.getElementById(outputDiv).innerHTML = "<br><p> archived log and report files as <a href=\"..\\logs\\core\\arch\\\" target=\"_blank\"> reference.</a></p><br>";

        // Process each line, display the report file content
        let displayContent = '';
        lines.forEach(line => {
            displayContent += line + '<br>';
        });

        class LogEntry {
            constructor(ip, bgpPeers, bgpPeersEstablished, vpnInstances, vpnPeers, vpnPeersEstablished, ospfFullState, ospfNonFullState) {
                this.ip = ip;
                this.bgpPeers = bgpPeers;
                this.bgpPeersEstablished = bgpPeersEstablished;
                this.vpnInstances = vpnInstances;
                this.vpnPeers = vpnPeers;
                this.vpnPeersEstablished = vpnPeersEstablished;
                this.ospfFullState = ospfFullState;
                this.ospfNonFullState = ospfNonFullState;
            }
        }
        const logEntries = [];
        const logContent = text;

        const logRegex = /Log file: logs\\core\\(\d{8}_\d{6}_([\d.]+)_\w+\.txt) Created\s*(?:BGP global: Total number of peers: (\d+) Peers in established state: (\d+)[\s\S]*?BGP VPN instance: (\d+) Total number of peers: (\d+) Peers in established state: (\d+))?[\s\S]*?OSPF Full State (\d+) . non-Full State: (\d+)/g;

        let match;
        while ((match = logRegex.exec(logContent)) !== null) {
            const [, , ip, bgpPeers, bgpPeersEstablished, vpnInstances, vpnPeers, vpnPeersEstablished, ospfFullState, ospfNonFullState] = match;
            const logEntry = new LogEntry(ip, parseInt(bgpPeers || 0), parseInt(bgpPeersEstablished || 0), parseInt(vpnInstances || 0), parseInt(vpnPeers || 0), parseInt(vpnPeersEstablished || 0), parseInt(ospfFullState || 0), parseInt(ospfNonFullState || 0));

            logEntries.push(logEntry);
        }

        console.log(logEntries);

        const tableBody = document.getElementById('logTableBody');

        logEntries.forEach(logEntry => {
            const row = document.createElement('tr');
            row.innerHTML = `
                                    <td>${logEntry.ip}</td>
                                    <td>${logEntry.bgpPeers}</td>
                                    <td>${logEntry.bgpPeersEstablished}</td>
                                    <td>${logEntry.vpnInstances}</td>
                                    <td>${logEntry.vpnPeers}</td>
                                    <td>${logEntry.vpnPeersEstablished}</td>
                                    <td>${logEntry.ospfFullState}</td>
                                    <td>${logEntry.ospfNonFullState}</td>
                                    `;
            tableBody.appendChild(row);
        });

        const ips = getAllIPs(logEntries);
        console.log(ips);

    } catch (error) {
        window.alert(error)
        //console.error('Error:', error);
    }
}