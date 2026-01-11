"use strict";

function refreshPage() {
  // Reload the page
  location.reload();
}

// iframe
function myIframe(id,file_src) {
    document.getElementById(id).src=file_src 
}

// myForm
function openForm() {
  document.getElementById("myForm").style.display = "block";
}

function closeForm() {
  document.getElementById("myForm").style.display = "none";
}

function startTime() {
	const today = new Date();
	let h = today.getHours();
	let m = today.getMinutes();
	let s = today.getSeconds();
	m = checkTime(m);
	s = checkTime(s);
	document.getElementById('txt').innerHTML =  h + ":" + m + ":" + s;
	setTimeout(startTime, 1000);
  }
  
  function checkTime(i) {
	if (i < 10) {i = "0" + i};  // add zero in front of numbers < 10
	return i;
  }
  function changeradioother() {
	var other = document.getElementById("other");
	other.value = document.getElementById("inputother").value;
  }

// fetch ajax
function fetch_ajax() {
    lastTouch = new Date();
    var url = 'scripts/knownissue.txt'

    $.ajax({
        url: url,
        dataType: 'test',
        timeout: 90000,
        success: function (data) {
            curData = data;
            updateList(data);
        },
        error: function (xhr, status, error) {
        }
    });
}

// clock
function startTime() {
    const today = new Date();
    let h = today.getHours();
    let m = today.getMinutes();
    let s = today.getSeconds();
    m = checkTime(m);
    s = checkTime(s);
    document.getElementById('txt').innerHTML =  h + ":" + m + ":" + s;
    setTimeout(startTime, 1000);
  }

  function checkTime(i) {
    if (i < 10) {i = "0" + i};  // add zero in front of numbers < 10
    return i;
  }

// load, open, save local file
function saveTextAsFile()
{
	var textToSave = document.getElementById("inputTextToSave").value;
	var textToSaveAsBlob = new Blob([textToSave], {type:"text/plain"});
	var textToSaveAsURL = window.URL.createObjectURL(textToSaveAsBlob);
	var fileNameToSaveAs = document.getElementById("inputFileNameToSaveAs").value;
 
	var downloadLink = document.createElement("a");
	downloadLink.download = fileNameToSaveAs;
	downloadLink.innerHTML = "Download File";
	downloadLink.href = textToSaveAsURL;
	downloadLink.onclick = destroyClickedElement;
	downloadLink.style.display = "none";
	document.body.appendChild(downloadLink);
 
	downloadLink.click();
}
 
function destroyClickedElement(event)
{
	document.body.removeChild(event.target);
}
 
function loadFileAsText()
{
	var fileToLoad = document.getElementById("fileToLoad").value;
	var fileToLoad = document.getElementById("fileToLoad").files[0];
 
	var fileReader = new FileReader();
	fileReader.onload = function(fileLoadedEvent) 
	{
		var textFromFileLoaded = fileLoadedEvent.target.result;
		document.getElementById("inputTextToSave").value = textFromFileLoaded;
	};
	fileReader.readAsText(fileToLoad, "UTF-8");
}


function loadDoc() {
	  const file=document.getElementById("loadDoc").value;	
	  const xhttp = new XMLHttpRequest();
	  xhttp.onreadystatechange = function() {
		if (this.readyState == 4 && this.status == 200) {
		  document.getElementById("loadDoc").innerHTML = this.responseText;
		}
	  };
	  xhttp.open("GET", file);
	  xhttp.setRequestHeader("Content-type", "test/UTF-8");
	  xhttp.send();
	}


function myFunction() {
  if (confirm("Are you sure you want to submit?")) {
    document.getElementById("checkform").submit();
  }}
	
async function getText(file,output) {
  let myObject = await fetch(file);
  let myText = await myObject.text();
  document.getElementById(output).innerHTML = myText;
}

function loadHtml(id,file){
	console.trace()
	const links = document.querySelectorAll('[id^=li]')
	//console.log(links)
	for (let i = 0; i < links.length; i++) {  links[i].classList.remove("active") ; } // removed all class "active" for all id^=li
	document.getElementById(id).className='active'

	const loadButton = document.getElementById(id);
	loadButton.addEventListener('click', function() {
	  const contentDiv = document.getElementById('page-content');
	  const xhr = new XMLHttpRequest();
	  xhr.open('GET', file, true); // Replace with the path to your other HTML file
	  xhr.onreadystatechange = function() {
		if (xhr.readyState === 4 && xhr.status === 200) {
		  contentDiv.innerHTML = xhr.responseText;
		}
	  };
	  xhr.send();
	});

 	$("#page-content").load(file,function(responseTxt,statusTxt,xhr){
		//if(statusTxt=="success")
		//    alert("Success!");
		if(statusTxt=="error")
			alert("Error: "+xhr.status+": "+xhr.statusText);
	}); 
}

function chartPlot(inputTable,outputDiv) {
  // Get the table reference
  console.log( inputTable,outputDiv);
  var table = document.getElementById(inputTable);
  var rows = table.getElementsByTagName('tr');
  const rowCount = table.getElementsByTagName('tbody')[0].rows.length;

  console.log( table,rows,rowCount,outputDiv);

// Arrays to store data for the chart
  var categories = ['Name'];
  var values = ['0d 0h 0m'];
  var colors = ['lightgray'];

// Loop through the table rows

  for (var i = 1; i < rowCount; i++) {
	//console.log(rows[i]);
    var cells = rows[i].getElementsByTagName('td');
    var row = table.rows[i];
    //console.log(cells,row);
    var category = cells['1'].textContent;
    var value = cells['0'].textContent;
    //var value = parseInt(cells['1'].textContent);

    //console.log(rows[i].style.display,category,value);

    //change chartColorClass by css-class 
    
    var chartColorClass = row.className ;
    //console.log(chartColorClass);
	if (chartColorClass == "highLight" ) {
        var color = 'Tomato';
	} else if (chartColorClass == "rowRecent" ) {
        var color = 'Orange';
	} else if (chartColorClass == "rowOld" ) {
        var color = 'Yellow';        
    } else {
        var color = 'lightgray';     
    }
    
    // Push data to respective arrays
    categories.push(category);
    values.push(value);
    colors.push(color);    
    //console.log(categories,values,colors);
  }

// Create the chart data
  var data = [
    {
      x: categories,
      y: values,
      base: "0d 0h 1m",
      marker: {
        color: colors,
        },
      type: 'bar'
    }
  ];

// Define the layout
  var layout = {
    title: 'DownTime Chart - Orion',
    height: 200,
  margin: {
    l: 100,
    r: 10,
    b: 30,
    t: 0,
    pad: 0
  },
  };

// Generate the chart
Plotly.newPlot(outputDiv, data, layout);

}

function countClassOccurrences(inputTable,outputTable) {
    // Get all table rows
    var table = document.getElementById(inputTable);
    var rows = table.getElementsByTagName('tr');
    //const rowCount = table.getElementsByTagName('tbody')[0].rows.length;


    // Object to store class counts -- object list
    var classCounts = {};

    // Loop through each row and collect class names
    for (var i = 0; i < rows.length; i++) {
        // Get class names of the current row
        var rowClassNames = rows[i].className.split(' ');
        //console.log(rowClassNames, rowClassNames.length);
        // Count occurrences of each class
        for (var j = 0; j < rowClassNames.length; j++) {
            var className = rowClassNames[j];
            if (className !== '') {
                classCounts[className] = (classCounts[className] || 0) + 1;
            }
        }
    }

    // Remove duplicates (if any)
    //classNames = Array.from(new Set(classNames));

    // Log the collected class names
    //console.log(inputTable,classCounts);

    // Display class counts in a table
    //var tbody 
    var disTable = document.getElementById(outputTable);
    //var tbody = disTable.getElementById('countDisplay');
    //var tbody = disTable.querySelector('tbody');
    var tbody = disTable.querySelector('tr');
    // Create a new row
    //var row = document.createElement('td');
    //var countCell = document.createElement('td');

    //console.log(tbody);

    for (var className in classCounts) {
        var count = classCounts[className];

        // Create cells for class name and count
        //var classNameCell = document.createElement('td');
        //classNameCell.textContent = className;
        var countCell = document.createElement('td');
        countCell.className = className;
        countCell.textContent = count;

        // Append cells to the row
        //row.appendChild(classNameCell);
        //row.appendChild(countCell);

        // Append row to the tbody
        tbody.appendChild(countCell);
    }

    //console.log(tbody);
    //document.getElementById('countDisplay').innerText = tbody;

    // return the function
    return;
}


function loadPage(url, element) {
  // Show loading message
  document.getElementById('loading-message').style.display = 'block';
  
  var xhttp = new XMLHttpRequest();
  xhttp.onreadystatechange = function() {
      if (this.readyState == 4 && this.status == 200) {
          document.getElementById('main-content').innerHTML = this.responseText;
          removeActiveClass(); // Remove active class from all links
          element.classList.add('active'); // Add active class to the clicked link
          // Hide loading message
          document.getElementById('loading-message').style.display = 'none';
          // Execute JavaScript code from the loaded page
          executeScriptFromLoadedPage();
      }
  };
  xhttp.open("GET", url, true);
  xhttp.send();
  return false; // prevent default link behavior
}

function removeActiveClass() {
  var navLinks = document.querySelectorAll('nav li a');
  navLinks.forEach(function(link) {
      link.classList.remove('active');
  });
}

function executeScriptFromLoadedPage() {
  // Get all script tags from the loaded content
  var scripts = document.getElementById('main-content').getElementsByTagName('script');
  // Loop through each script tag and execute its content
  for (var i = 0; i < scripts.length; i++) {
      eval(scripts[i].innerHTML);
  }
}

function displayJsonAsTable(data, parentElement, prefix = '') {
  const tbody = parentElement.querySelector('tbody');

  for (const key in data) {
      const tr = document.createElement('tr');

      const keyCell = document.createElement('td');
      keyCell.textContent = prefix + key;
      tr.appendChild(keyCell);

      const valueCell = document.createElement('td');
      if (typeof data[key] === 'object' && data[key] !== null) {
          if (Array.isArray(data[key])) {
              valueCell.textContent = ''; // Arrays are not directly displayed
              tr.appendChild(valueCell);
              tbody.appendChild(tr);
              // Display array elements in separate rows
              data[key].forEach((item, index) => {
                  displayJsonAsTable(item, parentElement, `${prefix}${key}[${index}].`);
              });
          } else {
              // Recursively display nested object
              displayJsonAsTable(data[key], parentElement, `${prefix}${key}.`);
          }
      } else {
          valueCell.textContent = data[key];
          tr.appendChild(valueCell);
          tbody.appendChild(tr);
      }
  }
}


function countTableRow(inputTable,outputDiv) {
  console.log("countTableRow function called.",inputTable,outputDiv);
  var table = document.getElementById(inputTable);
  var rows = table.getElementsByTagName('tr');
  const rowCount = rows.length - 1
  document.getElementById(outputDiv).innerHTML = rowCount
}

async function fetchAndReadTextFile(url, outputDiv) {
    try {
        const response = await fetch(url); // Fetch the file
        if (!response.ok) {
            throw new Error('Failed to fetch file');
        }
        const text = await response.text(); // Get the text content
        const lines = text.split('\n'); // Split text into lines

        // Process each line
        lines.forEach(line => {
            //console.log(line); // Or do whatever you need with each line
            document.getElementById(outputDiv).innerHTML += line + '<br>';
        });
    } catch (error) {
        console.error('Error:', error);
    }
}

function filterTable() {
  var input = document.getElementById('filterInput');
  var filter = input.value.toUpperCase();

  const tableCollect = document.getElementsByTagName('table');
  console.log(tableCollect);
  for (var t = 0; t < tableCollect.length; t++) {
    var table = tableCollect[t];
    var rows = table.getElementsByTagName('tr');
    var count = 0;
    const rowCount = table.getElementsByTagName('tbody')[0]?.rows.length || 0;

    for (var i = 0; i < rows.length; i++) {
      var cells = rows[i].getElementsByTagName('td');
      var shouldShowRow = false;

      for (var j = 0; j < cells.length; j++) {
        var cell = cells[j];
        if (cell) {
          var cellText = cell.textContent || cell.innerText;
          if (cellText.toUpperCase().indexOf(filter) > -1) {
            shouldShowRow = true;
            break;
          }
        }
      }

      rows[i].style.display = shouldShowRow ? '' : 'none';

      if (shouldShowRow) {
        count++;
      }
    }

    // var countElement = document.getElementById('row-count');
    // if (countElement) {
    //   countElement.textContent = "Total: " + rowCount.toString() + ' Matching: ' + count;
    // } else {
    //   console.warn("Element with ID 'row-count' not found.");
    // }
  }
}

function toggleAndDrawChart(buttonId, tagId, tableId) {
    const button = document.getElementById(buttonId);
    const visualization = document.getElementById(tagId);

    // Make sure both elements were found before adding a listener
    if (button && visualization) {
        button.addEventListener('click', function() {
            if (visualization.style.display === 'none') {
                // First, make the container visible
                visualization.style.display = 'block';

                // THEN, draw the chart inside the now-visible container
                piePlot(tableId, tagId); // Use the tagId passed to the function

            } else {
                // If visible, just hide it
                visualization.style.display = 'none';
            }
        });
    } else {
        console.error("Button or chart container not found. Check IDs:", buttonId, tagId);
    }
}


function piePlot(inputTable,outputDiv) {
  // Get the table reference
  var table = document.getElementById(inputTable);
  var rows = table.getElementsByTagName('tr');
  //console.log( inputTable,outputDiv,table);

  const rowCount = rows.length - 1; // need removed the header (hr) one
  //console.log( table,rows,rowCount,outputDiv);  
    
  const countHighLight = table.getElementsByClassName('highLight').length;
  const countRecent = table.getElementsByClassName('rowRecent').length;
  const countOld = table.getElementsByClassName('rowOld').length;
  const countOther = table.getElementsByClassName('rowOther').length;
  //const countHighLight = rowCount - countOther - countRecent - countOld // there has two 'hightLight' clase while site down

  console.log( "rowCount",rowCount,"countHighLight",countHighLight,"countRecent",countRecent,"countOld",countOld,"countOthers",countOther);


// Create the chart data
  var data = [{
	values: [countHighLight,countRecent,countOld,countOther],
	labels: ["last 12 hours","12-96 hours","4-7 days","more than 7 days"],
	marker: {
	  colors: ['Tomato','Orange','Yellow','lightgray']
	},
    type: 'pie',
	sort: false,
  }];

// Define the layout
  var layout = {
    title: 'DownTime Pie Chart - Orion',
    height: 200,
  margin: {
    l: 0,
    r: 0,
    b: 0,
    t: 0,
    pad: 0
  },
  };

// Generate the chart
Plotly.newPlot(outputDiv, data, layout);

}
// 20251009 Function to count unique sites and their types from a table and display in another table
function countSite(inputTable, outputDiv) {
  // Step 1: Get the input table by its ID
  var table = document.getElementById(inputTable);

  // Step 2: Select all <b> elements within the table
  const nodeList = table.querySelectorAll("b");         

  // Step 3: Map over the NodeList to create an array of objects containing text and parent <tr> class names
const dataArray = Array.from(nodeList, (element) => {
    const parentTr = element.closest("tr");
    if (!parentTr) return null;
    const tds = parentTr.getElementsByTagName('td');
    const durationCell = tds[0]; // First <td> for Duration
    const typeCell = tds.length > 2 ? tds[tds.length - 2] : null; // Second-to-last <td> for siteType
    const duration = durationCell ? durationCell.textContent.trim() : "";
    const siteType = typeCell ? typeCell.textContent.trim() : "";
    return {
      text: element.innerText.trim(),
      siteName: element.innerText.replace(' **Site Down**', '').trim(),
      duration: duration,
      siteType: siteType,
      className: parentTr ? parentTr.className : "",
    };
  }).filter(item => item !== null);

// Step 4: Remove duplicates based on siteName (across all classes)
  const uniqueArray = Array.from(
    new Set(dataArray.map((item) => item.siteName)) // Unique site names only
  ).map(siteName => {
    return dataArray.find(item => item.siteName === siteName);
  });

// Step 5: Extract unique site names, durations, and siteTypes
  const uniqueSitesByClass = {};
  uniqueArray.forEach(item => {
    if (!uniqueSitesByClass[item.className]) {
      uniqueSitesByClass[item.className] = new Map();
    }
    uniqueSitesByClass[item.className].set(item.siteName, {
      duration: item.duration,
      siteType: item.siteType
    });
  });
  console.log("uniqueSitesByClass:", uniqueSitesByClass);

  // Step 6: Count occurrences of each className
  const classCounts = uniqueArray.reduce((counts, item) => {
    counts[item.className] = (counts[item.className] || 0) + 1;
    return counts;
  }, {});
  console.log("SiteDownCounts:", classCounts);

  // Step 7: Update the output table or div
  var tbody = document.getElementById(outputDiv).querySelector('tbody');

  // Clear existing content to avoid duplication
  // tbody.innerHTML = '';

  // Add a header row with the total site count
  const headerRow = document.createElement("tr");
  const headerCell = document.createElement("th");
  headerCell.textContent = `Site: ${uniqueArray.length}`; // Total unique sites  
  // headerCell.textContent = `Site: ${Object.keys(classCounts).length}`; // Total unique classes with sites
  headerRow.appendChild(headerCell);

  // Add count cells for each class
  for (var className in classCounts) {
    var countCell = document.createElement('td');
    countCell.className = className; // Apply class for styling
    countCell.textContent = classCounts[className];
    headerRow.appendChild(countCell);
  }
  tbody.appendChild(headerRow);

// Add a new row for each site
  for (var className in uniqueSitesByClass) {
    const sitesMap = uniqueSitesByClass[className];
    for (let [siteName, { duration, siteType }] of sitesMap) {
      const sitesRow = document.createElement("tr");
      sitesRow.className = className; // Apply class for color
      sitesRow.style.fontSize = "120%"; // Slightly bigger font

      // Duration cell
      const durationCell = document.createElement("td");    
      durationCell.textContent = duration || "N/A";
      sitesRow.appendChild(durationCell);

      // SiteName cell
      const siteNameCell = document.createElement("td");
      const totalColumns = countColumns(outputDiv);
      siteNameCell.setAttribute("colspan", totalColumns - 1); // Span remaining columns        
      siteNameCell.textContent = siteName;
      sitesRow.appendChild(siteNameCell);

      // // SiteType cell
      // const siteTypeCell = document.createElement("td");
      // siteTypeCell.textContent = siteType || "N/A";
      // sitesRow.appendChild(siteTypeCell);

      tbody.appendChild(sitesRow);
    }
  }
}
// 20251010 Helper function to count total columns considering colspan
function countColumns(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return 0;
  const firstRow = table.getElementsByTagName('tr')[0];
  if (!firstRow) return 0;
  let columnCount = 0;
  const cells = firstRow.getElementsByTagName('th');
  for (let cell of cells) {
    const colspan = parseInt(cell.getAttribute('colspan')) || 1;
    columnCount += colspan;
  }
  const dataCells = firstRow.getElementsByTagName('td');
  for (let cell of dataCells) {
    const colspan = parseInt(cell.getAttribute('colspan')) || 1;
    columnCount += colspan;
  }
  return columnCount;
}

// 20251010 Function to copy rows containing "stack" from one table to another
function copyStackRows(inputTableId, outputTableId, countSpanId) {
const container = document.getElementById('interfaceStackDown');
    if (!container) return;

    // Clear old content
    container.innerHTML = '';

  // Step 1: Get the tables
  const sourceTable = document.getElementById(inputTableId);
  const targetTable = document.getElementById(outputTableId);
  if (!sourceTable || !targetTable) {
    console.error('One or both tables not found');
    return;
  }

  // Step 2: Get the tbody of the target table or create one if missing
  let targetTbody = targetTable.querySelector('tbody');
  if (!targetTbody) {
    targetTbody = document.createElement('tbody');
    targetTable.appendChild(targetTbody);
  }

  // Step 3: Clear existing rows in target tbody (optional, to avoid duplication)
  // targetTbody.innerHTML = '';

  // Step 4: Iterate through rows in source table

  const totalColumns = countColumns(outputTableId);  // Step 4.1: use colspan to span the new row
  
  const rows = sourceTable.getElementsByTagName('tr');
  let stackCount = 0;
  const filter_words = ['stack', 'teraspan','uplink'];
  const tds1Attribute = { 'colspan': totalColumns - 2, 'style':'text-align: left;'}; 

  for (let row of rows) {
    const link = row.querySelector('a');
    // 20251010 updated to include 'port' keyword
    if (link && filter_words.some(word => link.textContent.toLowerCase().includes(word.toLowerCase()))) {
      const clonedRow = row.cloneNode(true);
      // Step 6: Get the second and third <td> elements
      const tds = clonedRow.getElementsByTagName('td');
      if (tds.length >= 2) {
        // Set colspan=2 on the second <td>
        for (let [key, value] of Object.entries(tds1Attribute)) {
          tds[1].setAttribute(key, value);
        }
        tds[2].setAttribute('width', '12%' ); // Set width for the last column
        // Remove the third <td> to avoid duplication
        // if (tds.length >= 3) {
        //   tds[2].parentNode.removeChild(tds[2]);
        // }
      }

      targetTbody.appendChild(clonedRow);
      stackCount++;
    }
  }

  // Step 6: Update the count in the span
  const countSpan = document.getElementById(countSpanId);
  if (countSpan) {
    // countSpan.textContent = stackCount;
    console.log(`Copied ${stackCount} rows containing ${filter_words} `);
  } else {
    console.warn(countSpanId, ' span not found');
  }

  }

function displayPeerMaps(output_json) {
  fetch(output_json)
      .then(response => response.json())
      .then(data => {
          // Display hostname
          //console.log(data)
          document.getElementById('hostname').textContent = data.Hostname;

          // Populate BGP peers table
          const bgpPeers = data.BGP;
          console.log(bgpPeers)
          const bgpTable = document.getElementById('bgp-peers');
          bgpPeers.forEach(peer => {
              const row = document.createElement('tr');
              row.innerHTML = `
                  <td>${peer.VPN_instance}</td>
                  <td>${peer.local_router_id}</td>
                  <td>${peer.local_as_number}</td>
                  <td>${peer.Total_number_of_peers}</td>
                  <td>${peer.Peers_in_established_state}</td>
                  <td>${peer.Peer}</td>
              `;
              bgpTable.appendChild(row);
          });

          // Populate OSPF peers table
          const ospfPeers = data.OSPF_Peers;
          const ospfTable = document.getElementById('ospf-peers');
          ospfPeers.forEach(peer => {
              const row = document.createElement('tr');
              row.innerHTML = `
                  <td>${peer.RouterID}</td>
                  <td>${peer.Address}</td>
                  <td>${peer.Pri}</td>
                  <td>${peer.DeadTime}</td>
                  <td>${peer.State}</td>
                  <td>${peer.Interface}</td>
              `;
              ospfTable.appendChild(row);
          });
      })
      .catch(error => {
          console.error('Error loading JSON:', error);
      });
}

// Display tables for BGP and OSPF data
function renderBGPTable(bgpData) {
  const bgpTableBody = document.getElementById('bgpTable').querySelector('tbody');

  bgpData.forEach(instance => {
      const {
          VPN_instance,
          local_router_id,
          local_as_number,
          "Total number of peers": totalPeers,
          "Peers in established state": establishedPeers,
          Peer: peers
      } = instance;

      peers.forEach(peer => {
          const row = document.createElement('tr');

          // Highlight row if status is not "Established"
          if (peer.peer_status !== 'Established') {
              row.style.backgroundColor = 'yellow'; // Change color to red
          }

          row.innerHTML = `
              <td>${VPN_instance}</td>
              <td>${local_router_id}</td>
              <td>${local_as_number}</td>
              <td>${totalPeers}</td>
              <td>${establishedPeers}</td>
              <td>${peer.peer_IP}</td>
              <td>${peer.peer_AS}</td>
              <td>${peer.peer_uptime}</td>
              <td>${peer.peer_status}</td>
          `;
          bgpTableBody.appendChild(row);
      });
  });
}

// Function to render the OSPF table
function renderOSPFTable(ospfData) {
  const ospfTableBody = document.getElementById('ospfTable').querySelector('tbody');

  ospfData.forEach(process => {
      const {
          process: processId,
          "process router ID": routerId,
          area_info: areas
      } = process;

      areas.forEach(area => {
          const { Area, neighbor_info: neighbors } = area;

          neighbors.forEach(neighbor => {
              const row = document.createElement('tr');

          // Highlight row if status is not "Established"
          if (neighbor.State !== 'Full/') {
              row.style.backgroundColor = 'yellow'; // Change color to red
          }                
              row.innerHTML = `
                  <td>${processId}</td>
                  <td>${routerId}</td>
                  <td>${Area}</td>
                  <td>${neighbor["Router ID"]}</td>
                  <td>${neighbor.Address}</td>
                  <td>${neighbor.State}</td>
                  <td>${neighbor.Interface}</td>
              `;
              ospfTableBody.appendChild(row);
          });
      });
  });
}


async function getFileMetadata(url) {
  try {
      const response = await fetch(url, { method: 'HEAD' }); // Use HEAD request for metadata only

      if (response.ok) {
          const fileSize = response.headers.get('content-length');
          const lastModified = response.headers.get('last-modified');

          console.log(`File static: ${response.headers}`);
          console.log(`Last Modified: ${lastModified}`);

          return {
              size: fileSize,
              lastModified: lastModified ? new Date(lastModified).toLocaleString() : 'Unknown',
          };
      } else {
          console.error('Failed to retrieve file metadata');
          return null;
      }
  } catch (error) {
      console.error('Error fetching file metadata:', error);
      return null;
  }
}


// Function to fetch JSON and display in a new window
function showPeer(file_src, sourceDiv) {
  document.addEventListener("DOMContentLoaded", () => {
      const element = document.getElementById(sourceDiv);
      if (!element) {
          console.error(`Element with ID "${sourceDiv}" not found.`);
          return;
      }

      element.onclick = async function () {
          // Fetch file metadata
          const metadata = await getFileMetadata(file_src);
          const lastModified = metadata ? metadata.lastModified : "Unknown";

          fetch(file_src)
              .then(response => response.json())
              .then(data => {
                  const { hostname, host_ip, BGP, OSPF } = data;
    
                  // Open a new window
                  const newWindow = window.open("", "_blank", "width=900,height=600");

                  // Build HTML content
                  let content = `
                      <!DOCTYPE html>
                      <html lang="en">
                      <head>
                          <meta charset="UTF-8">
                          <meta name="viewport" content="width=device-width, initial-scale=1.0">
                          <title>BGP/OSPF Details</title>
                          <style>
                              body { font-family: Arial, sans-serif; padding: 20px; }
                              table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
                              th, td { border: 1px solid #ccc; padding: 5px; text-align: left; }
                              th { background-color: #f4f4f4; }
                              h2 { margin-top: 40px; }
                              .section-title {
                                  font-size: 1.2em;
                                  margin-top: 20px;
                                  font-weight: bold;
                              }
                          </style>
                      </head>
                      <body>
                          <h1>Routing Info - ${hostname} (${host_ip})</h1>
                          <p><strong>Timestamp:</strong> ${lastModified} <strong>Source file:</strong> <a href="${file_src}" target="_blank"> ${file_src}</a> </p>
                  `;

                  if (typeof(BGP) === 'string') {
                    console.error(BGP);
                    content +=  `<p> BGP is not configured. </p>`                    
                  } else if (!Array.isArray(BGP) || BGP.length == 0) {
                    console.error("BGP is not an array or empty:", BGP);
                    content +=  `<p> BGP is not an array or empty, not supported now. </p>`
                  } else {

                    // Count BGP VPN instances
                    const bgpVpnInstances = BGP.length;
                    // Count BGP peers
                    const bgpPeers = BGP.reduce((total, instance) => {
                        return total + (instance.Peer ? instance.Peer.length : 0);
                    }, 0);                
                    // Count BGP peers in "Established" status
                    const establishedBgpPeers = BGP.reduce((total, instance) => {
                      return total + (instance.Peer ? instance.Peer.filter(peer => peer.peer_status === "Established").length : 0);
                    }, 0);         

                    content +=  `                  
                          <div class="section-title">BGP VPN instance: ${bgpVpnInstances} ; BGP Peer:${bgpPeers} ; "Established" status: ${establishedBgpPeers}</div>    

                          <table id="bgpTable">
                                <thead>
                                    <tr>
                                        <th>VPN Instance</th>
                                        <th>Local Router ID</th>
                                        <th>Local AS Number</th>
                                        <th>Total Peers</th>
                                        <th>Established</th>
                                        <th>Peer IP</th>
                                        <th>Peer AS</th>
                                        <th>Uptime</th>
                                        <th>Status</th>
                                    </tr>
                                </thead>
                                <tbody>
                    `;
                    // Populate BGP Table
                    BGP.forEach(instance => {
                        const {
                            VPN_instance,
                            local_router_id,
                            local_as_number,
                            "Total number of peers": totalPeers,
                            "Peers in established state": establishedPeers,
                            Peer: peers
                        } = instance;

                        peers.forEach(peer => {
                            const rowColor = peer.peer_status !== "Established" ? "yellow" : "";
                            content += `
                                <tr style="background-color:${rowColor}">
                                    <td>${VPN_instance}</td>
                                    <td>${local_router_id}</td>
                                    <td>${local_as_number}</td>
                                    <td>${totalPeers}</td>
                                    <td>${establishedPeers}</td>
                                    <td>${peer.peer_IP}</td>
                                    <td>${peer.peer_AS}</td>
                                    <td>${peer.peer_uptime}</td>
                                    <td>${peer.peer_status}</td>
                                </tr>
                            `;
                        });
                    });

                    content += `
                                </tbody>
                            </table>
                    `;
                }

                // Add OSPF Table
                // content += `
                //   <div class="section-title">OSPF Peers </div>
                //   <table id="ospfTable">
                //   `;
                  if (typeof(OSPF) === 'string') {
                    console.error(OSPF);
                    content +=  `<p> OSPF is not configured. </p>`                    
                  } else if (!Array.isArray(OSPF) || OSPF.length == 0) {
                    console.error("OSPF is not an array or empty:", OSPF);
                    content +=  `<p> OSPF is not an array or empty, not supported now. </p>`
                  } else {
                                      
                    // Count OSPF processes
                    const ospfProcesses = OSPF.length;
                    // Count OSPF neighbors
                    const ospfNeighbors = OSPF.reduce((total, process) => {
                        return total + process.area_info.reduce((areaTotal, area) => {
                            return areaTotal + (area.neighbor_info ? area.neighbor_info.length : 0);
                        }, 0);
                    }, 0);   
                    // Count OSPF neighbors in "Full" state
                    const fullOspfNeighbors = OSPF.reduce((total, process) => {
                      return total + process.area_info.reduce((areaTotal, area) => {
                          return areaTotal + (area.neighbor_info ? area.neighbor_info.filter(neighbor => neighbor.State === "Full/").length : 0);
                      }, 0);
                    }, 0);     
                    
                    content += `
                          <div class="section-title">OSPF Processes: ${ospfProcesses} ;  Neighbors: ${ospfNeighbors};  'Full' State: ${fullOspfNeighbors}</div>
                          <table id="ospfTable">
                          <thead>
                              <tr>
                                  <th>Process</th>
                                  <th>Process Router ID</th>
                                  <th>Area</th>
                                  <th>Neighbor Router ID</th>
                                  <th>Neighbor Address</th>
                                  <th>Neighbor State</th>
                                  <th>Neighbor Interface</th>
                              </tr>
                          </thead>
                          <tbody>
                        `;
                      // Populate OSPF Table
                      OSPF.forEach(process => {
                          //console.log(OSPF)
                          const { process: processId, "process router ID": routerId, area_info: areas } = process;
                          areas.forEach(area => {
                            //console.log(areas)
                              const { Area, neighbor_info: neighbors } = area;
                              neighbors.forEach(neighbor => {
                                  //console.log(neighbors)
                                  const rowColor = neighbor.State !== "Full/" ? "yellow" : "";
                                  content += `
                                      <tr style="background-color:${rowColor}">
                                          <td>${processId}</td>
                                          <td>${routerId}</td>
                                          <td>${Area}</td>
                                          <td>${neighbor["Router ID"]}</td>
                                          <td>${neighbor.Address}</td>
                                          <td>${neighbor.State}</td>
                                          <td>${neighbor.Interface}</td>
                                      </tr>
                                  `;
                              });
                          });
                      });

                  content += `
                              </tbody>
                          </table>
                      </body>
                      </html>
                    `;
                  }

                  newWindow.document.open();
                  newWindow.document.write(content);
                  newWindow.document.close();
              })
              .catch(error => console.error("Error fetching routing info:", error));
      };
  });
}

function setupLinkRadioToggle(tableId, stateId) {
    const servicenowBaseUrl = "https://healthbc.service-now.com/nav_to.do?uri=%2F$sn_global_search_results.do%3Fsysparm_search%3D";
    const udtBaseUrl = "https://orion.net.mgmt/Orion/UDT/EndpointDetails.aspx?NetObject=UE-IP:VAL=";
    const websshBaseUrl = "/webssh?ip=";
    const radios = document.querySelectorAll(`input[name="link_type_${tableId}"]`);
    const state = document.getElementById(stateId);

    function updateLinks(mode) {
        const rows = document.querySelectorAll(`#${tableId} tbody tr`);
        rows.forEach((row) => {
          const links = row.querySelectorAll("a"); // Get all <a> tags in the row
          links.forEach((link, idx) => {
              if (!link.dataset.originalHref) {
                  link.dataset.originalHref = link.href;
              }
              if (mode === "Orion") {
                  link.href = link.dataset.originalHref;
              } else if (mode === "SNOW") {
                  if (tableId === "nodedownTable" || tableId === "interfacedownTable") {
                      // For the first link (device), use its text
                      if (idx === 0) {
                          const linkText = link.textContent.trim();
                          link.href = `${servicenowBaseUrl}${encodeURIComponent(linkText)}`;
                      } else {
                          // For all other links (site), use <b> if present, else link text
                          let linkText = "";
                          const bold = link.querySelector("b");
                          if (bold) {
                              linkText = bold.textContent.trim();
                          } else {
                              linkText = link.textContent.trim();
                          }
                          // Remove "Site Down" and asterisks
                          linkText = linkText.replace(/\*?\*?Site Down\*?\*?/gi, "").trim();
                          // Only update if linkText is not empty
                          if (linkText) {
                              link.href = `${servicenowBaseUrl}${encodeURIComponent(linkText)}`;
                          }
                      }
                  } else if (tableId === "alertTable") {
                      let linkText = link.textContent.trim();
                      let firstPart = linkText.split(/[\s·]/)[0];
                      link.href = `${servicenowBaseUrl}${encodeURIComponent(firstPart)}`;
                  }
              } else if (mode === "Orion_UDT") {
                  const ipCell = row.cells[row.cells.length - 1];
                  const ip = ipCell ? ipCell.textContent.trim() : "";
                  if (ip) {
                      link.href = `${udtBaseUrl}${ip}`;
                  }
              } else if (mode === "webssh") {
                  // Get IP from the value attribute of the second cell
                  const nodeInfoCell = row.cells[1];
                  let ip = "";
                  if (nodeInfoCell && nodeInfoCell.getAttribute("value")) {
                      const value = nodeInfoCell.getAttribute("value");
                      const match = value.match(/\d{1,3}(?:\.\d{1,3}){3}/);
                      if (match) ip = match[0];
                  }
                  if (ip) {
                      link.removeAttribute('href');
                      link.style.cursor = 'pointer';
                      link.onclick = function(e) {
                          e.preventDefault();
                          window.open(`/webssh?ip=${ip}`, '_blank');
                      };
                  }
              } else {
                  // Restore normal link behavior for other modes
                  link.onclick = null;
                  link.href = link.dataset.originalHref;
                  link.style.cursor = '';
              }
            });
        });
        if (state) state.textContent = mode;
    }

    radios.forEach(radio => {
        radio.addEventListener('change', function() {
            if (this.checked) {
                updateLinks(this.value);
            }
        });
    });

}

function linkToggle(inputId, toggleStateId, tableId) {
  // const orionBaseUrl = "https://orion.net.mgmt/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N:";
  const servicenowBaseUrl = "https://healthbc.service-now.com/nav_to.do?uri=%2F$sn_global_search_results.do%3Fsysparm_search%3D";
  // const orionSearchBaseUrl = "https://orion.net.mgmt/apps/search/?q=";

  const toggleInput = document.getElementById(inputId);
  const toggleState = document.getElementById(toggleStateId);

  if (!toggleInput || !toggleState) {
    console.error("Toggle input or state element not found.");
    return;
  }

  toggleInput.addEventListener("change", () => {
      toggleState.textContent = toggleInput.checked ? "ServiceNow" : "Orion";
      console.log(tableId, `Toggled to ${toggleInput.checked ? "ServiceNow" : "Orion"}`); ;
      toggleLinks(tableId, toggleInput.checked);
  });

  function toggleLinks(tableId, useServiceNow) {
    const rows = document.querySelectorAll(`#${tableId} tbody tr`);
    rows.forEach((row) => {
      const links = row.querySelectorAll("a"); // Find all <a> tags in the row
      links.forEach((link) => {
        const originalHref = link.dataset.originalHref || link.href;

        // Save the original link if not already saved
        if (!link.dataset.originalHref) {
          link.dataset.originalHref = originalHref;
        }

        if (useServiceNow) {
          const linkText = link.textContent.trim();
          link.href = `${servicenowBaseUrl}${encodeURIComponent(linkText)}`;
        } else {
          link.href = link.dataset.originalHref; // Restore the original link
        }
      });
    });
  }
}

function tableToScript() {
  console.log('tableToScript starting:');

  const tables = document.querySelectorAll("table");
  const ipList = Array.from(tables)
      .map(table => table.id)
      .filter(id => /^\d{1,3}(\.\d{1,3}){3}$/.test(id));

  console.log("Collected IP List:", ipList);

  ipList.forEach(ip => {
      const elementId = `${ip}_showPeer`;
      const scriptExists = document.querySelector(`script[data-ip="${ip}"]`);

      // Avoid appending duplicate scripts
      if (!scriptExists) {
        // Generate the script content
        const scriptContent = `showPeer('../logs/core/${ip}_routing_info.json', '${elementId}');`;

        console.log(`Generated Script Content for IP ${ip}:`, scriptContent);

        const scriptTag = document.createElement("script");
        scriptTag.textContent = scriptContent;
        scriptTag.setAttribute("data-ip", ip);
        document.body.appendChild(scriptTag);
    } else {
        console.warn(`Script for IP ${ip} already exists.`);
    }
  });
}

function updateWebSocketLink() {
  console.log("updateWebSocketLink function called.");

  // Find the selected radio button
  const selectedRadio = document.querySelector('input[name="interface_info"]:checked') || document.querySelector('input[name="node_info"]:checked');

  if (selectedRadio) {
      // Extract IP address using corrected regex
      let ipMatch = selectedRadio.value.trim().match(/\d{1,3}(\.\d{1,3}){3}/);
      if (ipMatch) {
          let ip = ipMatch[0];  // Get the first match
          console.log("Selected IP:", ip);

          // Update the href link dynamically
          let sshLink = document.getElementById("sshLink");
          if (sshLink) {
              sshLink.href = `/webssh?ip=${ip}`;
              sshLink.style.display = "inline"; // Make sure the link is visible
          } else {
              console.warn("sshLink element not found in the document.");
          }
      } else {
          alert("Error: No valid IP found!");
      }
  } else {
      alert("Please select an interface or node.");
  }
}

// 20251113
function toggleDisplay(buttonId, containerId) {
    const button = document.getElementById(buttonId);
    const container = document.getElementById(containerId);

    if (!button || !container) return;
    // ---- store the *original* text the first time we run ----
    if (!button.dataset.originalText) {
        button.dataset.originalText = button.textContent.trim();
    }

    button.addEventListener('click', function () {
        if (container.style.display === 'none' || container.style.display === '') {
            // --- SHOW ---
            container.style.display = 'block';
            // button.textContent = 'Hide';  // optional
        } else {
            // --- HIDE ---
            container.style.display = 'none';
            // button.textContent = button.dataset.originalText;  // optional
        }
    });
}

function toggleFilterRows(buttonId, tableId, keywords) {
    const button = document.getElementById(buttonId);
    const table = document.getElementById(tableId);
    if (!button || !table) return;

    // Store original button text
    if (!button.dataset.originalText) {
        button.dataset.originalText = button.textContent.trim();
    }

    let isFiltered = false;

    button.addEventListener('click', function () {
        isFiltered = !isFiltered;

        const rows = table.querySelectorAll('tbody tr');
        const lowerKeywords = keywords.map(k => k.toLowerCase());

        rows.forEach(row => {
            const text = (row.textContent || '').toLowerCase();
            const matches = lowerKeywords.some(kw => text.includes(kw));

            if (isFiltered) {
                row.style.display = matches ? '' : 'none';  // Show only matching
            } else {
                row.style.display = '';  // Show all
            }
        });

        // Update button text
        button.textContent = isFiltered ? 'Show All' : button.dataset.originalText;
    });
}

// Attach the function to radio buttons
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll('input[name="interface_info"], input[name="node_info"]').forEach(radio => {
      radio.addEventListener("change", updateWebSocketLink);
  });
});

console.log("my_javascript.js loaded success.");
